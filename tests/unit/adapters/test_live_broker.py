"""Tests for the KIS-backed live broker adapter."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from stock_trading_bot.adapters import LiveBroker, LiveBrokerConfig
from stock_trading_bot.core.enums import OrderEventType
from stock_trading_bot.core.models import OrderRequest


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeSession:
    def __init__(
        self,
        *,
        post_responses: list[_FakeResponse] | None = None,
        get_responses: list[_FakeResponse] | None = None,
    ) -> None:
        self.post_responses = deque(post_responses or [])
        self.get_responses = deque(get_responses or [])
        self.post_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> _FakeResponse:
        self.post_calls.append(
            {
                "url": url,
                "headers": dict(headers or {}),
                "json": dict(json or {}),
                "timeout": timeout,
            }
        )
        return self.post_responses.popleft()

    def get(
        self,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> _FakeResponse:
        self.get_calls.append(
            {
                "url": url,
                "headers": dict(headers or {}),
                "params": dict(params or {}),
                "timeout": timeout,
            }
        )
        return self.get_responses.popleft()


def _build_config() -> LiveBrokerConfig:
    return LiveBrokerConfig(
        api_key="app-key",
        api_secret="app-secret",
        account_no="12345678",
        account_product_code="01",
        api_environment="real",
        base_url="https://broker.example.com",
        websocket_url="wss://broker.example.com/ws",
    )


def _build_order_request() -> OrderRequest:
    return OrderRequest(
        order_request_id="req-live-001",
        instrument_id="005930",
        timestamp=datetime(2026, 4, 13, 9, 0, tzinfo=UTC),
        side="buy",
        order_type="market",
        quantity=Decimal("10"),
        price=Decimal("70000"),
        time_in_force="day",
        source_signal_id="sig-001",
        risk_check_ref="risk-001",
        broker_mode="live",
        request_reason="unit-test",
    )


def _build_query_response(
    *,
    total_filled_quantity: str,
    remaining_quantity: str,
    average_fill_price: str,
    rejected_quantity: str = "0",
    canceled: str = "N",
) -> _FakeResponse:
    return _FakeResponse(
        {
            "rt_cd": "0",
            "msg1": "ok",
            "output1": [
                {
                    "ord_dt": "20260413",
                    "ord_gno_brno": "00001",
                    "odno": "1234567890",
                    "pdno": "005930",
                    "ord_qty": "10",
                    "ord_tmd": "090001",
                    "tot_ccld_qty": total_filled_quantity,
                    "avg_prvs": average_fill_price,
                    "cncl_yn": canceled,
                    "rmn_qty": remaining_quantity,
                    "rjct_qty": rejected_quantity,
                    "infm_tmd": "091500",
                }
            ],
            "output2": {},
        }
    )


def test_live_broker_submits_market_order_with_kis_payload() -> None:
    session = _FakeSession(
        post_responses=[
            _FakeResponse(
                {
                    "access_token": "token-001",
                    "access_token_token_expired": "2099-01-01 00:00:00",
                }
            ),
            _FakeResponse({"HASH": "hash-001"}),
            _FakeResponse(
                {
                    "rt_cd": "0",
                    "msg1": "ok",
                    "output": {
                        "KRX_FWDG_ORD_ORGNO": "00001",
                        "ODNO": "1234567890",
                        "ORD_TMD": "090001",
                    },
                }
            ),
        ]
    )
    broker = LiveBroker(config=_build_config(), session=session)

    broker_order_id = broker.submit_order(_build_order_request())
    queued_events = broker.poll_events()

    assert broker_order_id == "00001:1234567890"
    assert [event.event_type for event in queued_events] == [OrderEventType.SUBMIT_SENT.value]
    assert session.post_calls[1]["url"].endswith("/uapi/hashkey")
    assert session.post_calls[2]["url"].endswith("/uapi/domestic-stock/v1/trading/order-cash")
    assert session.post_calls[2]["json"] == {
        "CANO": "12345678",
        "ACNT_PRDT_CD": "01",
        "PDNO": "005930",
        "ORD_DVSN": "01",
        "ORD_QTY": "10",
        "ORD_UNPR": "0",
        "EXCG_ID_DVSN_CD": "KRX",
        "CNDT_PRIC": "",
    }


def test_live_broker_polls_accepted_partial_and_full_fill_events() -> None:
    session = _FakeSession(
        post_responses=[
            _FakeResponse(
                {
                    "access_token": "token-001",
                    "access_token_token_expired": "2099-01-01 00:00:00",
                }
            ),
            _FakeResponse({"HASH": "hash-001"}),
            _FakeResponse(
                {
                    "rt_cd": "0",
                    "msg1": "ok",
                    "output": {
                        "KRX_FWDG_ORD_ORGNO": "00001",
                        "ODNO": "1234567890",
                        "ORD_TMD": "090001",
                    },
                }
            ),
        ],
        get_responses=[
            _build_query_response(
                total_filled_quantity="0",
                remaining_quantity="10",
                average_fill_price="0",
            ),
            _build_query_response(
                total_filled_quantity="4",
                remaining_quantity="6",
                average_fill_price="70125",
            ),
            _build_query_response(
                total_filled_quantity="10",
                remaining_quantity="0",
                average_fill_price="70300",
            ),
        ],
    )
    broker = LiveBroker(config=_build_config(), session=session)
    broker.submit_order(_build_order_request())

    submit_events = broker.poll_events()
    accepted_events = broker.poll_events()
    partial_fill_events = broker.poll_events()
    full_fill_events = broker.poll_events()

    assert [event.event_type for event in submit_events] == [OrderEventType.SUBMIT_SENT.value]
    assert [event.event_type for event in accepted_events] == [
        OrderEventType.BROKER_ACCEPTED.value
    ]
    assert [event.event_type for event in partial_fill_events] == [
        OrderEventType.PARTIAL_FILL.value
    ]
    assert partial_fill_events[0].filled_quantity == Decimal("4")
    assert partial_fill_events[0].remaining_quantity == Decimal("6")
    assert [event.event_type for event in full_fill_events] == [OrderEventType.FULL_FILL.value]
    assert full_fill_events[0].filled_quantity == Decimal("10")
    assert full_fill_events[0].remaining_quantity == Decimal("0")


def test_live_broker_confirms_cancel_after_cancel_request() -> None:
    session = _FakeSession(
        post_responses=[
            _FakeResponse(
                {
                    "access_token": "token-001",
                    "access_token_token_expired": "2099-01-01 00:00:00",
                }
            ),
            _FakeResponse({"HASH": "hash-001"}),
            _FakeResponse(
                {
                    "rt_cd": "0",
                    "msg1": "ok",
                    "output": {
                        "KRX_FWDG_ORD_ORGNO": "00001",
                        "ODNO": "1234567890",
                        "ORD_TMD": "090001",
                    },
                }
            ),
            _FakeResponse({"HASH": "hash-002"}),
            _FakeResponse({"rt_cd": "0", "msg1": "cancel accepted", "output": {}}),
        ],
        get_responses=[
            _build_query_response(
                total_filled_quantity="0",
                remaining_quantity="10",
                average_fill_price="0",
                canceled="Y",
            )
        ],
    )
    broker = LiveBroker(config=_build_config(), session=session)
    broker.submit_order(_build_order_request())
    broker.poll_events()

    broker.cancel_order("req-live-001")
    cancel_events = broker.poll_events()

    assert [event.event_type for event in cancel_events] == [OrderEventType.CANCEL_CONFIRMED.value]
    assert cancel_events[0].is_terminal is True
    assert session.post_calls[4]["url"].endswith("/uapi/domestic-stock/v1/trading/order-rvsecncl")


def test_live_broker_config_from_env_requires_credentials() -> None:
    with pytest.raises(ValueError, match="BROKER_API_KEY"):
        LiveBrokerConfig.from_env(
            {
                "BROKER_ENVIRONMENT": "real",
                "BROKER_API_SECRET": "secret",
                "BROKER_ACCOUNT_NO": "12345678",
                "BROKER_ACCOUNT_PRODUCT_CODE": "01",
            }
        )
