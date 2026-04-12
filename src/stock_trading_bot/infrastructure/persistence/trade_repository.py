"""Persist deterministic backtest results and trade records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from stock_trading_bot.infrastructure._serialization import dump_json

if TYPE_CHECKING:
    from stock_trading_bot.runtime.result_collector import RuntimeResult

FILL_EVENT_TYPES = frozenset({"partial_fill", "full_fill", "late_fill_after_cancel_request"})


@dataclass(slots=True, frozen=True, kw_only=True)
class TradeRecord:
    """Structured persisted record for one executed fill."""

    trade_sequence: int
    order_request_id: str
    order_event_id: str
    source_signal_id: str
    instrument_id: str
    timestamp: datetime
    side: str
    event_type: str
    requested_quantity: Decimal
    request_price: Decimal
    filled_quantity: Decimal
    filled_price_avg: Decimal
    remaining_quantity: Decimal
    gross_notional: Decimal
    broker_mode: str
    request_reason: str
    previous_state: str
    new_state: str


@dataclass(slots=True, kw_only=True)
class TradeRepository:
    """Persist runtime summaries and execution-derived trade artifacts."""

    result_directory: Path

    def save_runtime_result(
        self,
        runtime_result: RuntimeResult,
        *,
        event_log_path: Path | None = None,
    ) -> Path:
        """Persist the runtime result and derived trade artifacts."""

        self.result_directory.mkdir(parents=True, exist_ok=True)

        summary_path = self.result_directory / "summary.json"
        final_account_state_path = self.result_directory / "final_account_state.json"
        final_positions_path = self.result_directory / "final_positions.json"
        trade_records_path = self.result_directory / "trade_records.json"
        runtime_result_path = self.result_directory / "runtime_result.json"
        manifest_path = self.result_directory / "manifest.json"

        trade_records = self.build_trade_records(runtime_result)

        dump_json(summary_path, runtime_result.summary)
        dump_json(final_account_state_path, runtime_result.final_account_state)
        dump_json(final_positions_path, runtime_result.final_positions)
        dump_json(trade_records_path, trade_records)
        dump_json(runtime_result_path, runtime_result)
        dump_json(
            manifest_path,
            {
                "schema_version": 1,
                "artifact_type": "backtest_result",
                "summary_path": summary_path.name,
                "final_account_state_path": final_account_state_path.name,
                "final_positions_path": final_positions_path.name,
                "trade_records_path": trade_records_path.name,
                "runtime_result_path": runtime_result_path.name,
                "event_log_path": str(event_log_path) if event_log_path is not None else None,
            },
        )
        return self.result_directory

    @staticmethod
    def build_trade_records(runtime_result: RuntimeResult) -> tuple[TradeRecord, ...]:
        """Derive fill-only trade records from the processed runtime events."""

        order_requests_by_id = {
            order_request.order_request_id: order_request
            for order_request in runtime_result.order_requests
        }
        trade_records: list[TradeRecord] = []
        for trade_sequence, processed_order_event in enumerate(
            (
                processed_order_event
                for processed_order_event in runtime_result.processed_order_events
                if processed_order_event.order_event.event_type in FILL_EVENT_TYPES
            ),
            start=1,
        ):
            order_event = processed_order_event.order_event
            order_request = order_requests_by_id[order_event.order_request_id]
            trade_records.append(
                TradeRecord(
                    trade_sequence=trade_sequence,
                    order_request_id=order_request.order_request_id,
                    order_event_id=order_event.order_event_id,
                    source_signal_id=order_request.source_signal_id,
                    instrument_id=order_request.instrument_id,
                    timestamp=order_event.timestamp,
                    side=order_request.side,
                    event_type=order_event.event_type,
                    requested_quantity=order_request.quantity,
                    request_price=order_request.price,
                    filled_quantity=order_event.filled_quantity,
                    filled_price_avg=order_event.filled_price_avg,
                    remaining_quantity=order_event.remaining_quantity,
                    gross_notional=order_event.filled_quantity * order_event.filled_price_avg,
                    broker_mode=order_request.broker_mode,
                    request_reason=order_request.request_reason,
                    previous_state=processed_order_event.previous_state.value,
                    new_state=processed_order_event.new_state.value,
                )
            )
        return tuple(trade_records)
