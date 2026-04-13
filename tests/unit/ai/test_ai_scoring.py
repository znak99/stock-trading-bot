"""AI scoring tests for feature extraction, scoring, and ranking."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from stock_trading_bot.ai import (
    AdvancedRankingModel,
    BasicRankingModel,
    CandidateRanker,
    CoreFeatureSetBuilder,
)
from stock_trading_bot.core.models import CandidateSelectionResult, MarketDataSnapshot
from stock_trading_bot.market.services import (
    EnrichedHistoricalBar,
    HistoricalOhlcvBar,
    IndicatorPreprocessor,
)


def test_core_feature_set_builder_extracts_required_feature_groups() -> None:
    bars = _build_enriched_bars(
        instrument_id="A001",
        closes=tuple(Decimal("100") + Decimal(index) for index in range(20))
        + (Decimal("121"),),
        volumes=(1000,) * 20 + (2600,),
    )
    snapshot = _snapshot_from_bar(bars[-1])
    candidate = _candidate(
        instrument_id="A001",
        snapshot_ref=snapshot.snapshot_id,
        passed_filters=("not_halted", "min_trading_value"),
        failed_filters=("min_volume",),
    )
    builder = _feature_builder()

    feature_set = builder.build(candidate, snapshot, bars)

    assert feature_set.instrument_id == "A001"
    assert feature_set.feature_set_name == "core_feature_set_v1"
    assert feature_set.price_momentum.short_window == 3
    assert feature_set.price_momentum.short_return_rate > Decimal("0")
    assert feature_set.volume_liquidity.volume_ratio_to_average > Decimal("1")
    assert feature_set.breakout_position.distance_from_lookback_high > Decimal("0")
    assert feature_set.breakout_position.close_strength_ratio > Decimal("0.9")
    assert feature_set.trend_volatility.rsi_value > Decimal("50")
    assert feature_set.market_context.filter_pass_ratio == Decimal("2") / Decimal("3")
    assert feature_set.market_context.final_snapshot_score == Decimal("1")


def test_basic_ranking_model_scores_candidates_and_candidate_ranker_sorts_them() -> None:
    strong_bars = _build_enriched_bars(
        instrument_id="A001",
        closes=tuple(Decimal("100") + Decimal(index) for index in range(20))
        + (Decimal("121.5"),),
        volumes=(1000,) * 20 + (3200,),
    )
    weak_bars = _build_enriched_bars(
        instrument_id="A002",
        closes=tuple(Decimal("100") + (Decimal(index) * Decimal("0.6")) for index in range(20))
        + (Decimal("112"),),
        volumes=(1000,) * 20 + (1700,),
    )
    snapshots_by_instrument_id = {
        "A001": _snapshot_from_bar(strong_bars[-1]),
        "A002": _snapshot_from_bar(weak_bars[-1]),
    }
    candidates = (
        _candidate(
            instrument_id="A001",
            snapshot_ref=snapshots_by_instrument_id["A001"].snapshot_id,
        ),
        _candidate(
            instrument_id="A002",
            snapshot_ref=snapshots_by_instrument_id["A002"].snapshot_id,
        ),
    )
    bars_by_instrument_id = {
        "A001": strong_bars,
        "A002": weak_bars,
    }
    model = BasicRankingModel(
        recent_bars_provider=lambda instrument_id, snapshot: bars_by_instrument_id[instrument_id],
        core_feature_set_builder=_feature_builder(),
        group_weights={
            "price_momentum": Decimal("0.25"),
            "volume_liquidity": Decimal("0.20"),
            "breakout_position": Decimal("0.25"),
            "trend_volatility": Decimal("0.20"),
            "market_context": Decimal("0.10"),
        },
        price_return_cap=Decimal("0.15"),
        gap_rate_cap=Decimal("0.05"),
        volume_ratio_target=Decimal("2.0"),
        trading_value_ratio_target=Decimal("2.0"),
        breakout_distance_cap=Decimal("0.05"),
        close_strength_min=Decimal("0.8"),
        close_strength_target=Decimal("0.98"),
        trend_gap_cap=Decimal("0.10"),
        max_intraday_range_ratio=Decimal("0.12"),
        rsi_neutral_floor=Decimal("45"),
        rsi_neutral_ceiling=Decimal("75"),
        trend_alignment_cap=Decimal("0.05"),
    )

    ranked_scores = CandidateRanker(ranking_model=model).rank_candidates(
        candidates,
        snapshots_by_instrument_id=snapshots_by_instrument_id,
    )

    assert len(ranked_scores) == 2
    assert ranked_scores[0].instrument_id == "A001"
    assert ranked_scores[0].rank == 1
    assert ranked_scores[1].instrument_id == "A002"
    assert ranked_scores[1].rank == 2
    assert ranked_scores[0].score_value > ranked_scores[1].score_value
    assert all(score.model_name == "basic_ranking_model" for score in ranked_scores)
    assert all(score.feature_set_name == "core_feature_set_v1" for score in ranked_scores)


def test_advanced_ranking_model_penalizes_gap_and_overheated_candidates() -> None:
    stable_bars = _build_enriched_bars(
        instrument_id="A010",
        closes=tuple(Decimal("100") + Decimal(index) for index in range(20))
        + (Decimal("121"),),
        volumes=(1000,) * 20 + (2600,),
    )
    overheated_bars = _build_custom_enriched_bars(
        instrument_id="A011",
        close_prices=tuple(Decimal("100") + Decimal(index) for index in range(20))
        + (Decimal("121"),),
        volumes=(1000,) * 20 + (2600,),
        final_open=Decimal("128"),
        final_high=Decimal("136"),
        final_low=Decimal("118"),
        final_close=Decimal("121"),
    )
    snapshots_by_instrument_id = {
        "A010": _snapshot_from_bar(stable_bars[-1]),
        "A011": _snapshot_from_bar(overheated_bars[-1]),
    }
    candidates = (
        _candidate(
            instrument_id="A010",
            snapshot_ref=snapshots_by_instrument_id["A010"].snapshot_id,
        ),
        _candidate(
            instrument_id="A011",
            snapshot_ref=snapshots_by_instrument_id["A011"].snapshot_id,
        ),
    )
    bars_by_instrument_id = {
        "A010": stable_bars,
        "A011": overheated_bars,
    }
    advanced_model = AdvancedRankingModel(
        base_model=BasicRankingModel(
            recent_bars_provider=(
                lambda instrument_id, snapshot: bars_by_instrument_id[instrument_id]
            ),
            core_feature_set_builder=_feature_builder(),
            group_weights={
                "price_momentum": Decimal("0.25"),
                "volume_liquidity": Decimal("0.20"),
                "breakout_position": Decimal("0.25"),
                "trend_volatility": Decimal("0.20"),
                "market_context": Decimal("0.10"),
            },
            price_return_cap=Decimal("0.15"),
            gap_rate_cap=Decimal("0.05"),
            volume_ratio_target=Decimal("2.0"),
            trading_value_ratio_target=Decimal("2.0"),
            breakout_distance_cap=Decimal("0.05"),
            close_strength_min=Decimal("0.8"),
            close_strength_target=Decimal("0.98"),
            trend_gap_cap=Decimal("0.10"),
            max_intraday_range_ratio=Decimal("0.12"),
            rsi_neutral_floor=Decimal("45"),
            rsi_neutral_ceiling=Decimal("75"),
            trend_alignment_cap=Decimal("0.05"),
        ),
        preferred_gap_rate=Decimal("0.02"),
        max_gap_penalty_rate=Decimal("0.08"),
        overbought_rsi_floor=Decimal("78"),
        overbought_rsi_ceiling=Decimal("95"),
        soft_intraday_range_ratio=Decimal("0.05"),
        hard_intraday_range_ratio=Decimal("0.18"),
        breakout_buffer_cap=Decimal("0.03"),
        volume_bonus_cap=Decimal("0.75"),
        breakout_bonus_weight=Decimal("0.06"),
        volume_bonus_weight=Decimal("0.05"),
        gap_penalty_weight=Decimal("0.12"),
        rsi_penalty_weight=Decimal("0.08"),
        volatility_penalty_weight=Decimal("0.10"),
    )

    ranked_scores = CandidateRanker(ranking_model=advanced_model).rank_candidates(
        candidates,
        snapshots_by_instrument_id=snapshots_by_instrument_id,
    )

    assert [score.instrument_id for score in ranked_scores] == ["A010", "A011"]
    assert ranked_scores[0].model_name == "advanced_ranking_model"
    assert ranked_scores[0].score_value > ranked_scores[1].score_value
    assert "gap_penalty=" in ranked_scores[1].score_reason_summary
    assert "volatility_penalty=" in ranked_scores[1].score_reason_summary


def _feature_builder() -> CoreFeatureSetBuilder:
    return CoreFeatureSetBuilder(
        feature_set_name="core_feature_set_v1",
        momentum_windows=(3, 5, 10),
        volume_average_window=5,
        trading_value_average_window=5,
        breakout_lookback_days=20,
        short_moving_average_name="sma_5",
        long_moving_average_name="sma_20",
        rsi_indicator_name="rsi_14",
    )


def _candidate(
    *,
    instrument_id: str,
    snapshot_ref: str,
    passed_filters: tuple[str, ...] = ("not_halted", "min_trading_value", "min_volume"),
    failed_filters: tuple[str, ...] = (),
) -> CandidateSelectionResult:
    return CandidateSelectionResult(
        candidate_id=f"candidate:{instrument_id}",
        instrument_id=instrument_id,
        timestamp=datetime(2026, 4, 21),
        filter_policy_name="default_filter_policy",
        passed=True,
        eligibility_reason="eligible",
        market_snapshot_ref=snapshot_ref,
        passed_filters=passed_filters,
        failed_filters=failed_filters,
    )


def _snapshot_from_bar(bar: EnrichedHistoricalBar) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        snapshot_id=f"snapshot:{bar.instrument_id}:{bar.timestamp.date().isoformat()}",
        instrument_id=bar.instrument_id,
        timestamp=bar.timestamp,
        open_price=bar.open_price,
        high_price=bar.high_price,
        low_price=bar.low_price,
        close_price=bar.close_price,
        volume=bar.volume,
        trading_value=bar.trading_value,
        change_rate=bar.change_rate,
        is_final=True,
        session_phase="MARKET_CLOSE_PROCESS",
    )


def _build_enriched_bars(
    *,
    instrument_id: str,
    closes: tuple[Decimal, ...],
    volumes: tuple[int, ...],
) -> tuple[EnrichedHistoricalBar, ...]:
    ohlcv_bars = tuple(
        HistoricalOhlcvBar(
            instrument_id=instrument_id,
            timestamp=datetime(2026, 4, 1) + timedelta(days=index),
            open_price=close_price - Decimal("1"),
            high_price=close_price + Decimal("1"),
            low_price=close_price - Decimal("2"),
            close_price=close_price,
            volume=volumes[index],
            trading_value=close_price * Decimal(volumes[index]),
            change_rate=(
                Decimal("0")
                if index == 0
                else (close_price / closes[index - 1]) - Decimal("1")
            ),
        )
        for index, close_price in enumerate(closes)
    )
    return IndicatorPreprocessor().preprocess(ohlcv_bars)


def _build_custom_enriched_bars(
    *,
    instrument_id: str,
    close_prices: tuple[Decimal, ...],
    volumes: tuple[int, ...],
    final_open: Decimal,
    final_high: Decimal,
    final_low: Decimal,
    final_close: Decimal,
):
    ohlcv_bars = [
        HistoricalOhlcvBar(
            instrument_id=instrument_id,
            timestamp=datetime(2026, 4, 1) + timedelta(days=index),
            open_price=close_price - Decimal("1"),
            high_price=close_price + Decimal("1"),
            low_price=close_price - Decimal("2"),
            close_price=close_price,
            volume=volumes[index],
            trading_value=close_price * Decimal(volumes[index]),
            change_rate=(
                Decimal("0")
                if index == 0
                else (close_price / close_prices[index - 1]) - Decimal("1")
            ),
        )
        for index, close_price in enumerate(close_prices[:-1])
    ]
    ohlcv_bars.append(
        HistoricalOhlcvBar(
            instrument_id=instrument_id,
            timestamp=datetime(2026, 4, 1) + timedelta(days=len(close_prices) - 1),
            open_price=final_open,
            high_price=final_high,
            low_price=final_low,
            close_price=final_close,
            volume=volumes[-1],
            trading_value=final_close * Decimal(volumes[-1]),
            change_rate=(final_close / close_prices[-2]) - Decimal("1"),
        )
    )
    return IndicatorPreprocessor().preprocess(tuple(ohlcv_bars))
