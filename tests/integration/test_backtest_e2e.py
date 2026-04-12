"""End-to-end backtest tests."""

from __future__ import annotations

import csv
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from stock_trading_bot.app.run_backtest import main, run_backtest


def test_run_backtest_completes_entry_partial_exit_full_exit_and_pnl(tmp_path: Path) -> None:
    _write_e2e_fixture(tmp_path / "005930.csv")

    result = run_backtest(data_directory=tmp_path)
    event_counter = Counter(
        processed_order_event.order_event.event_type
        for processed_order_event in result.processed_order_events
    )

    assert len(result.phase_history) == 24 * 4
    assert result.summary.initial_equity == Decimal("10000000")
    assert result.summary.order_request_count == 3
    assert result.summary.buy_order_count == 1
    assert result.summary.sell_order_count == 2
    assert result.summary.fill_event_count == 3
    assert result.summary.active_position_count == 0
    assert result.summary.closed_position_count == 1
    assert result.summary.unrealized_pnl == Decimal("0")
    assert result.summary.total_pnl == result.summary.final_equity - result.summary.initial_equity
    assert result.summary.realized_pnl > result.summary.total_pnl
    assert (
        result.summary.realized_pnl - result.summary.accumulated_buy_commission
        == result.summary.total_pnl
    )
    assert result.summary.total_pnl > Decimal("0")
    assert result.final_account_state.total_equity == result.summary.final_equity
    assert result.final_account_state.realized_pnl == result.summary.realized_pnl
    assert [order_request.side for order_request in result.order_requests] == [
        "buy",
        "sell",
        "sell",
    ]
    assert [order_request.price for order_request in result.order_requests] == [
        Decimal("121"),
        Decimal("125"),
        Decimal("123"),
    ]
    assert {"buy", "partial_sell", "sell"}.issubset(
        {signal.signal_type for signal in result.signals}
    )
    assert event_counter == Counter(
        {
            "submit_enqueued": 3,
            "submit_sent": 3,
            "broker_accepted": 3,
            "full_fill": 3,
        }
    )


def test_backtest_main_prints_summary(tmp_path: Path, capsys) -> None:
    _write_e2e_fixture(tmp_path / "005930.csv")

    exit_code = main(["--data-dir", str(tmp_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Backtest completed." in output
    assert "initial_equity=10000000" in output
    assert "orders=3" in output
    assert "fill_events=3" in output
    assert "realized_pnl=" in output
    assert "return_rate=" in output
    assert "buy_commission=" in output
    assert "closed_positions=1" in output


def _write_e2e_fixture(path: Path) -> None:
    fieldnames = ("date", "open", "high", "low", "close", "volume")
    rows: list[dict[str, str]] = []
    start_date = date(2024, 1, 1)

    for offset in range(20):
        base_price = Decimal("100") + Decimal(offset)
        rows.append(
            {
                "date": (start_date + timedelta(days=offset)).isoformat(),
                "open": str(base_price - Decimal("1")),
                "high": str(base_price),
                "low": str(base_price - Decimal("2")),
                "close": str(base_price - Decimal("0.5")),
                "volume": "1000000",
            }
        )

    rows.extend(
        (
            {
                "date": date(2024, 1, 21).isoformat(),
                "open": "119",
                "high": "121",
                "low": "118",
                "close": "120",
                "volume": "2500000",
            },
            {
                "date": date(2024, 1, 22).isoformat(),
                "open": "121",
                "high": "127",
                "low": "120",
                "close": "126",
                "volume": "1200000",
            },
            {
                "date": date(2024, 1, 23).isoformat(),
                "open": "125",
                "high": "126",
                "low": "117",
                "close": "118",
                "volume": "1100000",
            },
            {
                "date": date(2024, 1, 24).isoformat(),
                "open": "123",
                "high": "124",
                "low": "121",
                "close": "122",
                "volume": "1050000",
            },
        )
    )

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
