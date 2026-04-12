"""Strategy entry and exit components."""

from .entry import BreakoutSwingEntryStrategy
from .exit import ConservativeExitPolicy
from .services import CloseConfirmationEngine, CloseConfirmationResult, SignalFactory

__all__ = [
    "BreakoutSwingEntryStrategy",
    "CloseConfirmationEngine",
    "CloseConfirmationResult",
    "ConservativeExitPolicy",
    "SignalFactory",
]
