"""Candidate selection result contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True, kw_only=True)
class CandidateSelectionResult:
    """Filter-chain outcome and eligibility reasons for a candidate."""

    candidate_id: str
    instrument_id: str
    timestamp: datetime
    filter_policy_name: str
    passed: bool
    eligibility_reason: str
    market_snapshot_ref: str
    passed_filters: tuple[str, ...] = field(default_factory=tuple)
    failed_filters: tuple[str, ...] = field(default_factory=tuple)

