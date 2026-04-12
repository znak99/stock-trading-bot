"""Trading-session clock and canonical session phase normalization."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

CANONICAL_SESSION_PHASES = (
    "PRE_MARKET",
    "INTRADAY_MONITOR",
    "MARKET_CLOSE_PROCESS",
    "NEXT_OPEN_EXECUTION",
)

SESSION_PHASE_ALIASES = {
    "INTRADAY": "INTRADAY_MONITOR",
    "CLOSE": "MARKET_CLOSE_PROCESS",
    "NEXT_OPEN": "NEXT_OPEN_EXECUTION",
}

DEFAULT_RUNTIME_SEQUENCE = (
    "PRE_MARKET",
    "NEXT_OPEN_EXECUTION",
    "INTRADAY_MONITOR",
    "MARKET_CLOSE_PROCESS",
)


@dataclass(slots=True, frozen=True, kw_only=True)
class SessionStep:
    """Single runtime step for one trading date and one session phase."""

    trading_date: date
    phase: str


@dataclass(slots=True, kw_only=True)
class SessionClock:
    """Iterate trading dates and normalized session phases for a runtime loop."""

    start_date: date
    end_date: date
    session_phases: tuple[str, ...] = CANONICAL_SESSION_PHASES
    runtime_phase_sequence: tuple[str, ...] = DEFAULT_RUNTIME_SEQUENCE

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date.")

        normalized_session_phases = tuple(
            self.normalize_phase_name(phase_name)
            for phase_name in self.session_phases
        )
        if len(set(normalized_session_phases)) != len(normalized_session_phases):
            raise ValueError("session_phases must not contain duplicate values.")
        self.session_phases = normalized_session_phases

        normalized_runtime_sequence = tuple(
            self.normalize_phase_name(phase_name)
            for phase_name in self.runtime_phase_sequence
        )
        if any(phase_name not in self.session_phases for phase_name in normalized_runtime_sequence):
            raise ValueError("runtime_phase_sequence must be a subset of session_phases.")
        self.runtime_phase_sequence = normalized_runtime_sequence

    def iter_trading_dates(self) -> Iterator[date]:
        """Yield trading dates from start to end, inclusive."""

        current_date = self.start_date
        while current_date <= self.end_date:
            yield current_date
            current_date += timedelta(days=1)

    def iter_session_steps(self) -> Iterator[SessionStep]:
        """Yield runtime steps in the configured execution order."""

        for trading_date in self.iter_trading_dates():
            for phase_name in self.runtime_phase_sequence:
                yield SessionStep(trading_date=trading_date, phase=phase_name)

    @classmethod
    def normalize_phase_name(cls, phase_name: str) -> str:
        """Normalize runtime aliases to canonical phase names."""

        normalized_phase_name = SESSION_PHASE_ALIASES.get(phase_name, phase_name)
        if normalized_phase_name not in CANONICAL_SESSION_PHASES:
            supported = ", ".join(CANONICAL_SESSION_PHASES)
            raise ValueError(f"Unsupported session phase {phase_name!r}. Supported: {supported}.")
        return normalized_phase_name

    @classmethod
    def normalized_phases(cls, phase_names: Sequence[str]) -> tuple[str, ...]:
        """Return a tuple of normalized phase names."""

        return tuple(cls.normalize_phase_name(phase_name) for phase_name in phase_names)
