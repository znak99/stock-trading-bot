"""KIS Open API-backed live broker adapter."""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests

from stock_trading_bot.core.enums import OrderEventType
from stock_trading_bot.core.models import OrderEvent, OrderRequest

_TOKEN_PATH: Final[str] = "/oauth2/tokenP"
_HASHKEY_PATH: Final[str] = "/uapi/hashkey"
_ORDER_CASH_PATH: Final[str] = "/uapi/domestic-stock/v1/trading/order-cash"
_ORDER_CANCEL_PATH: Final[str] = "/uapi/domestic-stock/v1/trading/order-rvsecncl"
_ORDER_QUERY_PATH: Final[str] = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"

_ORDER_TR_IDS: Final[dict[str, dict[str, str]]] = {
    "real": {
        "buy": "TTTC0012U",
        "sell": "TTTC0011U",
        "cancel": "TTTC0013U",
        "query_inner": "TTTC0081R",
        "query_before": "CTSC9215R",
    },
    "demo": {
        "buy": "VTTC0012U",
        "sell": "VTTC0011U",
        "cancel": "VTTC0013U",
        "query_inner": "VTTC0081R",
        "query_before": "VTSC9215R",
    },
}
_DEFAULT_BASE_URLS: Final[dict[str, str]] = {
    "real": "https://openapi.koreainvestment.com:9443",
    "demo": "https://openapivts.koreainvestment.com:29443",
}
_DEFAULT_WEBSOCKET_URLS: Final[dict[str, str]] = {
    "real": "wss://ops.koreainvestment.com:21000",
    "demo": "wss://ops.koreainvestment.com:31000",
}


class LiveBrokerConfigurationError(ValueError):
    """Raised when the live broker is missing required runtime configuration."""


class LiveBrokerApiError(RuntimeError):
    """Raised when the upstream broker API call fails at the HTTP or payload layer."""


@dataclass(slots=True, frozen=True, kw_only=True)
class LiveBrokerConfig:
    """Resolved KIS Open API configuration for the live broker adapter."""

    api_key: str
    api_secret: str
    account_no: str
    account_product_code: str
    api_environment: str = "real"
    base_url: str = _DEFAULT_BASE_URLS["real"]
    websocket_url: str = _DEFAULT_WEBSOCKET_URLS["real"]
    exchange_id: str = "KRX"
    hts_id: str = ""
    order_query_scope: str = "inner"
    order_query_side_filter: str = "00"
    order_query_fill_filter: str = "00"
    order_query_sort_order: str = "01"
    order_query_asset_filter: str = "00"
    order_poll_lookback_days: int = 0

    def __post_init__(self) -> None:
        if self.api_environment not in _ORDER_TR_IDS:
            raise LiveBrokerConfigurationError(
                "api_environment must be one of {'real', 'demo'}. "
                f"api_environment={self.api_environment!r}"
            )
        if not self.account_no:
            raise LiveBrokerConfigurationError("account_no is required.")
        if not self.account_product_code:
            raise LiveBrokerConfigurationError("account_product_code is required.")
        if self.order_query_scope not in {"inner", "before"}:
            raise LiveBrokerConfigurationError(
                "order_query_scope must be 'inner' or 'before'. "
                f"order_query_scope={self.order_query_scope!r}"
            )
        if self.order_poll_lookback_days < 0:
            raise LiveBrokerConfigurationError(
                "order_poll_lookback_days cannot be negative. "
                f"order_poll_lookback_days={self.order_poll_lookback_days!r}"
            )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LiveBrokerConfig:
        """Build broker configuration from environment variables."""

        env = dict(os.environ if environ is None else environ)
        api_environment = env.get("BROKER_ENVIRONMENT", "real").strip().lower() or "real"
        missing = [
            variable_name
            for variable_name in (
                "BROKER_API_KEY",
                "BROKER_API_SECRET",
                "BROKER_ACCOUNT_NO",
                "BROKER_ACCOUNT_PRODUCT_CODE",
            )
            if not env.get(variable_name)
        ]
        if missing:
            missing_values = ", ".join(missing)
            raise LiveBrokerConfigurationError(
                "Missing required live broker environment variables: "
                f"{missing_values}."
            )

        return cls(
            api_key=env["BROKER_API_KEY"].strip(),
            api_secret=env["BROKER_API_SECRET"].strip(),
            account_no=env["BROKER_ACCOUNT_NO"].strip(),
            account_product_code=env["BROKER_ACCOUNT_PRODUCT_CODE"].strip(),
            api_environment=api_environment,
            base_url=env.get("BROKER_BASE_URL", "").strip()
            or _DEFAULT_BASE_URLS.get(api_environment, _DEFAULT_BASE_URLS["real"]),
            websocket_url=env.get("BROKER_WS_URL", "").strip()
            or _DEFAULT_WEBSOCKET_URLS.get(
                api_environment,
                _DEFAULT_WEBSOCKET_URLS["real"],
            ),
            exchange_id=env.get("BROKER_EXCHANGE_ID", "KRX").strip() or "KRX",
            hts_id=env.get("BROKER_HTS_ID", "").strip(),
            order_query_scope=env.get("BROKER_ORDER_QUERY_SCOPE", "inner").strip() or "inner",
            order_query_side_filter=env.get("BROKER_ORDER_QUERY_SIDE_FILTER", "00").strip()
            or "00",
            order_query_fill_filter=env.get("BROKER_ORDER_QUERY_FILL_FILTER", "00").strip()
            or "00",
            order_query_sort_order=env.get("BROKER_ORDER_QUERY_SORT_ORDER", "01").strip()
            or "01",
            order_query_asset_filter=env.get("BROKER_ORDER_QUERY_ASSET_FILTER", "00").strip()
            or "00",
            order_poll_lookback_days=int(env.get("BROKER_ORDER_POLL_LOOKBACK_DAYS", "0")),
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class _BearerToken:
    value: str
    expires_at: datetime

    def is_expired(self, *, now: datetime) -> bool:
        return now >= (self.expires_at - timedelta(minutes=5))


@dataclass(slots=True, kw_only=True)
class _TrackedLiveOrder:
    order_request: OrderRequest
    broker_order_id: str
    order_orgno: str
    order_number: str
    submitted_at: datetime
    accepted_emitted: bool = False
    cancel_requested: bool = False
    terminal_emitted: bool = False
    last_filled_quantity: Decimal = Decimal("0")
    last_remaining_quantity: Decimal | None = None
    last_fill_price_avg: Decimal = Decimal("0")

    @property
    def remaining_quantity(self) -> Decimal:
        if self.last_remaining_quantity is not None:
            return self.last_remaining_quantity
        return self.order_request.quantity - self.last_filled_quantity


class _KisRestClient:
    """Small REST helper with token refresh and KIS header generation."""

    def __init__(
        self,
        *,
        config: LiveBrokerConfig,
        session: requests.Session | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._session = session or requests.Session()
        self._now_provider = now_provider or (lambda: datetime.now(tz=UTC))
        self._token: _BearerToken | None = None

    def post(
        self,
        path: str,
        *,
        tr_id: str,
        payload: Mapping[str, Any],
        include_hashkey: bool,
    ) -> dict[str, Any]:
        headers = self._build_headers(tr_id=tr_id)
        if include_hashkey:
            headers["hashkey"] = self._issue_hashkey(payload)
        response = self._session.post(
            f"{self._config.base_url}{path}",
            headers=headers,
            json=dict(payload),
            timeout=10,
        )
        return self._parse_response(response, path=path)

    def get(self, path: str, *, tr_id: str, params: Mapping[str, Any]) -> dict[str, Any]:
        headers = self._build_headers(tr_id=tr_id)
        response = self._session.get(
            f"{self._config.base_url}{path}",
            headers=headers,
            params=dict(params),
            timeout=10,
        )
        return self._parse_response(response, path=path)

    def _build_headers(self, *, tr_id: str) -> dict[str, str]:
        token = self._ensure_token()
        return {
            "content-type": "application/json",
            "accept": "application/json",
            "charset": "UTF-8",
            "authorization": f"Bearer {token.value}",
            "appkey": self._config.api_key,
            "appsecret": self._config.api_secret,
            "tr_id": tr_id,
            "custtype": "P",
            "tr_cont": "",
        }

    def _ensure_token(self) -> _BearerToken:
        current_time = self._now_provider()
        if self._token is not None and not self._token.is_expired(now=current_time):
            return self._token

        response = self._session.post(
            f"{self._config.base_url}{_TOKEN_PATH}",
            headers={"content-type": "application/json", "accept": "application/json"},
            json={
                "grant_type": "client_credentials",
                "appkey": self._config.api_key,
                "appsecret": self._config.api_secret,
            },
            timeout=10,
        )
        payload = self._parse_response(response, path=_TOKEN_PATH)
        try:
            access_token = str(payload["access_token"])
            expires_at = datetime.strptime(
                str(payload["access_token_token_expired"]),
                "%Y-%m-%d %H:%M:%S",
            ).replace(tzinfo=UTC)
        except KeyError as error:
            raise LiveBrokerApiError(
                "Token response is missing a required field. "
                f"missing={error.args[0]!r}"
            ) from error

        self._token = _BearerToken(value=access_token, expires_at=expires_at)
        return self._token

    def _issue_hashkey(self, payload: Mapping[str, Any]) -> str:
        token = self._ensure_token()
        response = self._session.post(
            f"{self._config.base_url}{_HASHKEY_PATH}",
            headers={
                "content-type": "application/json",
                "accept": "application/json",
                "authorization": f"Bearer {token.value}",
                "appkey": self._config.api_key,
                "appsecret": self._config.api_secret,
            },
            json=dict(payload),
            timeout=10,
        )
        payload_body = self._parse_response(response, path=_HASHKEY_PATH)
        hash_value = payload_body.get("HASH")
        if not hash_value:
            raise LiveBrokerApiError("Hashkey response did not include HASH.")
        return str(hash_value)

    @staticmethod
    def _parse_response(response: requests.Response, *, path: str) -> dict[str, Any]:
        if response.status_code != 200:
            raise LiveBrokerApiError(
                "Broker HTTP request failed. "
                f"path={path}, status_code={response.status_code}, body={response.text}"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise LiveBrokerApiError(
                f"Broker response body is not valid JSON. path={path}, body={response.text}"
            ) from error
        if not isinstance(payload, dict):
            raise LiveBrokerApiError(
                f"Broker response body must be a mapping. path={path}, body={payload!r}"
            )
        return payload


class LiveBroker:
    """Live broker adapter that normalizes KIS REST responses into OrderEvent objects."""

    mode = "live"

    def __init__(
        self,
        *,
        config: LiveBrokerConfig,
        session: requests.Session | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._now_provider = now_provider or (lambda: datetime.now(tz=UTC))
        self._market_timezone = ZoneInfo("Asia/Seoul")
        self._client = _KisRestClient(
            config=config,
            session=session,
            now_provider=self._now_provider,
        )
        self._tracked_orders: dict[str, _TrackedLiveOrder] = {}
        self._queued_events: deque[OrderEvent] = deque()

    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        session: requests.Session | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> LiveBroker:
        """Build the live broker from environment variables."""

        return cls(
            config=LiveBrokerConfig.from_env(environ),
            session=session,
            now_provider=now_provider,
        )

    def submit_order(self, order_request: OrderRequest) -> str:
        """Submit a live order to KIS and queue the broker-facing lifecycle events."""

        if order_request.order_request_id in self._tracked_orders:
            raise ValueError(f"Duplicate order_request_id={order_request.order_request_id!r}.")

        order_payload = self._build_order_payload(order_request)
        tr_id = self._resolve_order_tr_id(order_request.side)
        response = self._client.post(
            _ORDER_CASH_PATH,
            tr_id=tr_id,
            payload=order_payload,
            include_hashkey=True,
        )

        output = response.get("output")
        output_mapping = output if isinstance(output, Mapping) else {}
        order_orgno = str(output_mapping.get("KRX_FWDG_ORD_ORGNO", "")).strip()
        order_number = str(output_mapping.get("ODNO", "")).strip()
        if response.get("rt_cd") == "0" and order_orgno and order_number:
            broker_order_id = self._compose_broker_order_id(order_orgno, order_number)
        else:
            broker_order_id = f"kis:rejected:{order_request.order_request_id}"

        tracked_order = _TrackedLiveOrder(
            order_request=order_request,
            broker_order_id=broker_order_id,
            order_orgno=order_orgno,
            order_number=order_number,
            submitted_at=order_request.timestamp,
        )
        self._tracked_orders[order_request.order_request_id] = tracked_order

        self._queued_events.append(
            self._build_event(
                tracked_order=tracked_order,
                event_type=OrderEventType.SUBMIT_SENT,
                timestamp=order_request.timestamp,
                filled_quantity=Decimal("0"),
                filled_price_avg=Decimal("0"),
                remaining_quantity=order_request.quantity,
                event_message="live broker accepted the submission request payload",
                is_terminal=False,
            )
        )

        if response.get("rt_cd") != "0":
            tracked_order.terminal_emitted = True
            self._queued_events.append(
                self._build_event(
                    tracked_order=tracked_order,
                    event_type=OrderEventType.BROKER_REJECTED,
                    timestamp=order_request.timestamp,
                    filled_quantity=Decimal("0"),
                    filled_price_avg=Decimal("0"),
                    remaining_quantity=order_request.quantity,
                    event_message=str(response.get("msg1", "live broker rejected order")),
                    is_terminal=True,
                )
            )

        return broker_order_id

    def cancel_order(self, order_request_id: str) -> None:
        """Send a cancel request for the tracked broker order."""

        tracked_order = self._get_tracked_order(order_request_id)
        if tracked_order.terminal_emitted:
            raise ValueError(
                "Cannot cancel a terminal live order. "
                f"order_request_id={order_request_id!r}"
            )
        if not tracked_order.order_orgno or not tracked_order.order_number:
            raise ValueError(
                "Cannot cancel an order without a resolved KIS order number. "
                f"order_request_id={order_request_id!r}"
            )

        cancel_payload = {
            "CANO": self._config.account_no,
            "ACNT_PRDT_CD": self._config.account_product_code,
            "KRX_FWDG_ORD_ORGNO": tracked_order.order_orgno,
            "ORGN_ODNO": tracked_order.order_number,
            "ORD_DVSN": self._map_order_type(tracked_order.order_request.order_type),
            "RVSE_CNCL_DVSN_CD": "02",
            "ORD_QTY": self._format_decimal(tracked_order.remaining_quantity),
            "ORD_UNPR": self._format_price(tracked_order.order_request),
            "QTY_ALL_ORD_YN": "Y",
            "EXCG_ID_DVSN_CD": self._config.exchange_id,
        }
        response = self._client.post(
            _ORDER_CANCEL_PATH,
            tr_id=_ORDER_TR_IDS[self._config.api_environment]["cancel"],
            payload=cancel_payload,
            include_hashkey=True,
        )
        tracked_order.cancel_requested = True

        if response.get("rt_cd") != "0":
            self._queued_events.append(
                self._build_event(
                    tracked_order=tracked_order,
                    event_type=OrderEventType.CANCEL_REJECTED,
                    timestamp=self._now_provider(),
                    filled_quantity=tracked_order.last_filled_quantity,
                    filled_price_avg=tracked_order.last_fill_price_avg,
                    remaining_quantity=tracked_order.remaining_quantity,
                    event_message=str(response.get("msg1", "live broker cancel rejected")),
                    is_terminal=False,
                )
            )

    def poll_events(self) -> Sequence[OrderEvent]:
        """Poll KIS order status snapshots and emit normalized incremental events."""

        if self._queued_events:
            events = tuple(self._queued_events)
            self._queued_events.clear()
            return events

        normalized_events: list[OrderEvent] = []
        for tracked_order in self._tracked_orders.values():
            if tracked_order.terminal_emitted:
                continue
            order_snapshot = self._query_order_snapshot(tracked_order)
            if order_snapshot is None:
                continue
            normalized_events.extend(self._normalize_order_snapshot(tracked_order, order_snapshot))

        return tuple(normalized_events)

    def _query_order_snapshot(self, tracked_order: _TrackedLiveOrder) -> Mapping[str, Any] | None:
        query_end_date = self._today_kst()
        query_start_date = tracked_order.submitted_at.astimezone(self._market_timezone).date()
        query_start_date -= timedelta(days=self._config.order_poll_lookback_days)
        if query_start_date > query_end_date:
            query_start_date = query_end_date

        response = self._client.get(
            _ORDER_QUERY_PATH,
            tr_id=self._resolve_query_tr_id(),
            params={
                "CANO": self._config.account_no,
                "ACNT_PRDT_CD": self._config.account_product_code,
                "INQR_STRT_DT": query_start_date.strftime("%Y%m%d"),
                "INQR_END_DT": query_end_date.strftime("%Y%m%d"),
                "SLL_BUY_DVSN_CD": self._resolve_query_side_filter(
                    tracked_order.order_request.side
                ),
                "PDNO": tracked_order.order_request.instrument_id,
                "CCLD_DVSN": self._config.order_query_fill_filter,
                "INQR_DVSN": self._config.order_query_sort_order,
                "INQR_DVSN_3": self._config.order_query_asset_filter,
                "ORD_GNO_BRNO": tracked_order.order_orgno,
                "ODNO": tracked_order.order_number,
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
                "EXCG_ID_DVSN_CD": self._config.exchange_id,
            },
        )
        output_rows = response.get("output1", [])
        if not isinstance(output_rows, list):
            return None

        matching_rows = [
            row
            for row in output_rows
            if isinstance(row, Mapping)
            and str(row.get("odno", "")).strip() == tracked_order.order_number
        ]
        if not matching_rows:
            return None

        return matching_rows[-1]

    def _normalize_order_snapshot(
        self,
        tracked_order: _TrackedLiveOrder,
        order_snapshot: Mapping[str, Any],
    ) -> list[OrderEvent]:
        order_quantity = self._to_decimal(
            order_snapshot.get("ord_qty") or order_snapshot.get("tot_ord_qty")
        )
        total_filled_quantity = self._to_decimal(order_snapshot.get("tot_ccld_qty"))
        remaining_quantity = self._to_decimal(order_snapshot.get("rmn_qty"))
        if remaining_quantity == Decimal("0") and total_filled_quantity < order_quantity:
            remaining_quantity = order_quantity - total_filled_quantity
        rejected_quantity = self._to_decimal(order_snapshot.get("rjct_qty"))
        average_fill_price = self._to_decimal(order_snapshot.get("avg_prvs"))
        is_canceled = self._is_affirmative(order_snapshot.get("cncl_yn"))
        event_timestamp = self._parse_snapshot_timestamp(
            order_snapshot,
            fallback=tracked_order.submitted_at,
        )
        normalized_events: list[OrderEvent] = []

        if rejected_quantity > Decimal("0") and not tracked_order.terminal_emitted:
            tracked_order.last_remaining_quantity = remaining_quantity
            tracked_order.terminal_emitted = True
            normalized_events.append(
                self._build_event(
                    tracked_order=tracked_order,
                    event_type=OrderEventType.BROKER_REJECTED,
                    timestamp=event_timestamp,
                    filled_quantity=Decimal("0"),
                    filled_price_avg=Decimal("0"),
                    remaining_quantity=(
                        remaining_quantity
                        if remaining_quantity > Decimal("0")
                        else tracked_order.order_request.quantity
                    ),
                    event_message="live broker reported rejected quantity",
                    is_terminal=True,
                )
            )
            return normalized_events

        if not tracked_order.cancel_requested and not tracked_order.accepted_emitted:
            tracked_order.accepted_emitted = True
            normalized_events.append(
                self._build_event(
                    tracked_order=tracked_order,
                    event_type=OrderEventType.BROKER_ACCEPTED,
                    timestamp=event_timestamp,
                    filled_quantity=tracked_order.last_filled_quantity,
                    filled_price_avg=tracked_order.last_fill_price_avg,
                    remaining_quantity=remaining_quantity,
                    event_message="live broker accepted order",
                    is_terminal=False,
                )
            )

        if total_filled_quantity > tracked_order.last_filled_quantity:
            tracked_order.last_filled_quantity = total_filled_quantity
            tracked_order.last_remaining_quantity = remaining_quantity
            tracked_order.last_fill_price_avg = average_fill_price
            if tracked_order.cancel_requested:
                event_type = OrderEventType.LATE_FILL_AFTER_CANCEL_REQUEST
            elif remaining_quantity == Decimal("0"):
                event_type = OrderEventType.FULL_FILL
            else:
                event_type = OrderEventType.PARTIAL_FILL

            normalized_events.append(
                self._build_event(
                    tracked_order=tracked_order,
                    event_type=event_type,
                    timestamp=event_timestamp,
                    filled_quantity=total_filled_quantity,
                    filled_price_avg=average_fill_price,
                    remaining_quantity=remaining_quantity,
                    event_message="live broker fill update",
                    is_terminal=remaining_quantity == Decimal("0"),
                )
            )
            if remaining_quantity == Decimal("0"):
                tracked_order.terminal_emitted = True
                return normalized_events

        if tracked_order.cancel_requested and is_canceled and not tracked_order.terminal_emitted:
            tracked_order.last_remaining_quantity = remaining_quantity
            tracked_order.terminal_emitted = True
            normalized_events.append(
                self._build_event(
                    tracked_order=tracked_order,
                    event_type=OrderEventType.CANCEL_CONFIRMED,
                    timestamp=event_timestamp,
                    filled_quantity=tracked_order.last_filled_quantity,
                    filled_price_avg=tracked_order.last_fill_price_avg,
                    remaining_quantity=remaining_quantity,
                    event_message="live broker cancel confirmed",
                    is_terminal=True,
                )
            )

        return normalized_events

    def _build_order_payload(self, order_request: OrderRequest) -> dict[str, str]:
        self._validate_order_request(order_request)
        payload = {
            "CANO": self._config.account_no,
            "ACNT_PRDT_CD": self._config.account_product_code,
            "PDNO": order_request.instrument_id,
            "ORD_DVSN": self._map_order_type(order_request.order_type),
            "ORD_QTY": self._format_decimal(order_request.quantity),
            "ORD_UNPR": self._format_price(order_request),
            "EXCG_ID_DVSN_CD": self._config.exchange_id,
            "CNDT_PRIC": "",
        }
        if order_request.side == "sell":
            payload["SLL_TYPE"] = "01"
        return payload

    def _validate_order_request(self, order_request: OrderRequest) -> None:
        if order_request.time_in_force != "day":
            raise ValueError(
                "LiveBroker currently supports only day orders. "
                f"time_in_force={order_request.time_in_force!r}"
            )
        if order_request.order_type not in {"market", "limit"}:
            raise ValueError(
                "LiveBroker currently supports only market and limit orders. "
                f"order_type={order_request.order_type!r}"
            )
        if order_request.quantity <= Decimal("0"):
            raise ValueError(
                "Order quantity must be positive. "
                f"quantity={order_request.quantity!r}"
            )

    def _get_tracked_order(self, order_request_id: str) -> _TrackedLiveOrder:
        try:
            return self._tracked_orders[order_request_id]
        except KeyError as error:
            raise ValueError(f"Unknown order_request_id={order_request_id!r}.") from error

    def _resolve_order_tr_id(self, side: str) -> str:
        return _ORDER_TR_IDS[self._config.api_environment][side]

    def _resolve_query_tr_id(self) -> str:
        scope_key = "query_inner" if self._config.order_query_scope == "inner" else "query_before"
        return _ORDER_TR_IDS[self._config.api_environment][scope_key]

    @staticmethod
    def _compose_broker_order_id(order_orgno: str, order_number: str) -> str:
        return f"{order_orgno}:{order_number}"

    def _build_event(
        self,
        *,
        tracked_order: _TrackedLiveOrder,
        event_type: OrderEventType,
        timestamp: datetime,
        filled_quantity: Decimal,
        filled_price_avg: Decimal,
        remaining_quantity: Decimal,
        event_message: str,
        is_terminal: bool,
    ) -> OrderEvent:
        return OrderEvent(
            order_event_id=f"event-{uuid4().hex}",
            order_request_id=tracked_order.order_request.order_request_id,
            timestamp=timestamp,
            event_type=event_type.value,
            broker_order_id=tracked_order.broker_order_id,
            filled_quantity=filled_quantity,
            filled_price_avg=filled_price_avg,
            remaining_quantity=remaining_quantity,
            event_message=event_message,
            is_terminal=is_terminal,
        )

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        normalized_value = value.quantize(Decimal("1"))
        return format(normalized_value, "f")

    def _format_price(self, order_request: OrderRequest) -> str:
        if order_request.order_type == "market":
            return "0"
        return self._format_decimal(order_request.price)

    @staticmethod
    def _map_order_type(order_type: str) -> str:
        mapping = {
            "limit": "00",
            "market": "01",
        }
        try:
            return mapping[order_type]
        except KeyError as error:
            raise ValueError(f"Unsupported order_type={order_type!r}.") from error

    @staticmethod
    def _map_side_filter(side: str) -> str:
        return "02" if side == "buy" else "01"

    def _resolve_query_side_filter(self, side: str) -> str:
        if self._config.order_query_side_filter != "00":
            return self._config.order_query_side_filter
        return self._map_side_filter(side)

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        if value in (None, "", " "):
            return Decimal("0")
        try:
            return Decimal(str(value).strip())
        except (InvalidOperation, ValueError) as error:
            raise LiveBrokerApiError(f"Failed to parse decimal value: {value!r}") from error

    @staticmethod
    def _is_affirmative(value: Any) -> bool:
        normalized = str(value or "").strip().upper()
        return normalized in {"Y", "1", "TRUE"}

    def _today_kst(self) -> date:
        return self._now_provider().astimezone(self._market_timezone).date()

    def _parse_snapshot_timestamp(
        self,
        order_snapshot: Mapping[str, Any],
        *,
        fallback: datetime,
    ) -> datetime:
        order_date = str(order_snapshot.get("ord_dt", "")).strip()
        time_candidates = (
            str(order_snapshot.get("infm_tmd", "")).strip(),
            str(order_snapshot.get("ord_tmd", "")).strip(),
        )
        for time_candidate in time_candidates:
            if len(order_date) == 8 and len(time_candidate) == 6 and time_candidate.isdigit():
                try:
                    parsed_timestamp = datetime.strptime(
                        f"{order_date}{time_candidate}",
                        "%Y%m%d%H%M%S",
                    ).replace(tzinfo=self._market_timezone)
                    return parsed_timestamp.astimezone(UTC)
                except ValueError:
                    continue
        return fallback
