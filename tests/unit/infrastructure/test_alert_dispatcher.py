"""Alert dispatcher tests."""

from __future__ import annotations

from datetime import UTC, datetime

from stock_trading_bot.infrastructure.notifications import (
    AlertDispatcher,
    AlertNotification,
    RecordingAlertNotifier,
)


def test_alert_dispatcher_sends_alerts_to_registered_notifiers() -> None:
    notifier = RecordingAlertNotifier()
    dispatcher = AlertDispatcher(notifiers=(notifier,))
    alert = AlertNotification.create(
        timestamp=datetime(2026, 4, 13, 9, 30, tzinfo=UTC),
        severity="warning",
        code="duplicate_order_blocked",
        title="Duplicate active order blocked",
        message="duplicate order detected",
        metadata={"instrument_id": "005930", "side": "buy"},
    )

    dispatcher.dispatch_all((alert,))

    assert notifier.notifications == [alert]
