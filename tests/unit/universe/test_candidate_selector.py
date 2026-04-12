"""Tests for universe selection filters and candidate selection."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stock_trading_bot.core.models import Instrument, MarketDataSnapshot
from stock_trading_bot.universe import CandidateSelector, DefaultFilterPolicy


def _build_instrument(*, instrument_id: str = "instr-001", is_active: bool = True) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        symbol=f"SYM-{instrument_id[-3:]}",
        name=f"Instrument {instrument_id[-3:]}",
        market="KOSPI",
        asset_type="equity",
        sector="general",
        is_etf=False,
        is_active=is_active,
    )


def _build_snapshot(
    *,
    instrument_id: str = "instr-001",
    snapshot_id: str = "snap-001",
    trading_value: str = "2500000000",
    volume: int = 250000,
) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        snapshot_id=snapshot_id,
        instrument_id=instrument_id,
        timestamp=datetime(2026, 4, 12, 15, 30, tzinfo=UTC),
        open_price=Decimal("10000"),
        high_price=Decimal("10300"),
        low_price=Decimal("9900"),
        close_price=Decimal("10200"),
        volume=volume,
        trading_value=Decimal(trading_value),
        change_rate=Decimal("0.02"),
        is_final=True,
        session_phase="MARKET_CLOSE_PROCESS",
    )


def test_candidate_selector_records_all_passed_filters() -> None:
    selector = CandidateSelector(
        filter_policy=DefaultFilterPolicy(
            min_trading_value=Decimal("1000000000"),
            min_volume=100000,
        )
    )

    result = selector.select_candidate(_build_instrument(), _build_snapshot())
    evaluation_log = selector.get_evaluation_log()

    assert result.passed is True
    assert result.filter_policy_name == "default_filter_policy"
    assert result.eligibility_reason == "passed_all_filters"
    assert result.passed_filters == (
        "trading_status:trading_allowed",
        "trading_value:trading_value_gte_1000000000",
        "liquidity:volume_gte_100000",
    )
    assert result.failed_filters == ()

    assert len(evaluation_log) == 3
    assert all(entry.passed for entry in evaluation_log)
    assert evaluation_log[0].reason == "trading_allowed"
    assert evaluation_log[1].market_snapshot_ref == "snap-001"


def test_candidate_selector_records_failed_filters_and_reasons() -> None:
    selector = CandidateSelector(
        filter_policy=DefaultFilterPolicy(
            min_trading_value=Decimal("1000000000"),
            min_volume=100000,
        )
    )

    result = selector.select_candidate(
        _build_instrument(is_active=False),
        _build_snapshot(trading_value="500000000", volume=50000),
    )
    evaluation_log = selector.get_evaluation_log()

    assert result.passed is False
    assert result.passed_filters == ()
    assert result.failed_filters == (
        "trading_status:trading_halted_or_inactive",
        "trading_value:trading_value_below_threshold(actual=500000000,min=1000000000)",
        "liquidity:volume_below_threshold(actual=50000,min=100000)",
    )
    assert result.eligibility_reason == "trading_status:trading_halted_or_inactive"

    assert len(evaluation_log) == 3
    assert [entry.filter_name for entry in evaluation_log] == [
        "trading_status",
        "trading_value",
        "liquidity",
    ]
    assert [entry.passed for entry in evaluation_log] == [False, False, False]
    assert evaluation_log[-1].reason == "volume_below_threshold(actual=50000,min=100000)"


def test_select_candidates_evaluates_multiple_instruments() -> None:
    selector = CandidateSelector(
        filter_policy=DefaultFilterPolicy(
            min_trading_value=Decimal("1000000000"),
            min_volume=100000,
        )
    )
    instruments = (
        _build_instrument(instrument_id="instr-001"),
        _build_instrument(instrument_id="instr-002", is_active=False),
    )
    snapshots_by_instrument_id = {
        "instr-001": _build_snapshot(instrument_id="instr-001", snapshot_id="snap-001"),
        "instr-002": _build_snapshot(
            instrument_id="instr-002",
            snapshot_id="snap-002",
            trading_value="400000000",
            volume=80000,
        ),
    }

    results = selector.select_candidates(instruments, snapshots_by_instrument_id)

    assert len(results) == 2
    assert [result.passed for result in results] == [True, False]
    assert results[0].candidate_id == "candidate:instr-001:snap-001"
    assert results[1].market_snapshot_ref == "snap-002"


def test_select_candidates_requires_snapshot_for_every_instrument() -> None:
    selector = CandidateSelector(
        filter_policy=DefaultFilterPolicy(
            min_trading_value=Decimal("1000000000"),
            min_volume=100000,
        )
    )

    with pytest.raises(ValueError, match="Snapshot is required"):
        selector.select_candidates((_build_instrument(),), {})
