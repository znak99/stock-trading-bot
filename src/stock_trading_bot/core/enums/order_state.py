"""Order state enum."""

from __future__ import annotations

from enum import StrEnum


class OrderState(StrEnum):
    """Canonical order states defined by the detailed design spec."""

    CREATED = "created"
    PENDING_SUBMIT = "pending_submit"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"

