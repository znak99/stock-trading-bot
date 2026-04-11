"""Order event type enum."""

from __future__ import annotations

from enum import StrEnum


class OrderEventType(StrEnum):
    """Canonical order events defined by the detailed design spec."""

    SUBMIT_ENQUEUED = "submit_enqueued"
    SUBMIT_SENT = "submit_sent"
    SUBMIT_TIMEOUT = "submit_timeout"
    BROKER_ACCEPTED = "broker_accepted"
    BROKER_REJECTED = "broker_rejected"
    PARTIAL_FILL = "partial_fill"
    FULL_FILL = "full_fill"
    CANCEL_REQUESTED = "cancel_requested"
    CANCEL_CONFIRMED = "cancel_confirmed"
    CANCEL_REJECTED = "cancel_rejected"
    EXPIRED = "expired"
    CANCELED_BEFORE_SUBMIT = "canceled_before_submit"
    INTERNAL_REJECTED = "internal_rejected"
    LATE_FILL_AFTER_CANCEL_REQUEST = "late_fill_after_cancel_request"

