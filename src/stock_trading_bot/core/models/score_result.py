"""AI score result contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(slots=True, kw_only=True)
class ScoreResult:
    """Normalized AI score and ranking outcome."""

    score_id: str
    instrument_id: str
    timestamp: datetime
    model_name: str
    model_version: str
    score_value: Decimal
    rank: int
    feature_set_name: str
    candidate_ref: str
    score_reason_summary: str

