"""Operational alert notification dispatchers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

import requests


@dataclass(slots=True, frozen=True, kw_only=True)
class AlertNotification:
    """Structured operational alert notification."""

    alert_id: str
    timestamp: datetime
    severity: str
    code: str
    title: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        timestamp: datetime,
        severity: str,
        code: str,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> AlertNotification:
        """Create an alert with a generated identifier."""

        return cls(
            alert_id=f"alert-{uuid4().hex}",
            timestamp=timestamp,
            severity=severity,
            code=code,
            title=title,
            message=message,
            metadata=dict(metadata or {}),
        )


@runtime_checkable
class AlertNotifier(Protocol):
    """Protocol for alert transports."""

    def notify(self, alert: AlertNotification) -> None:
        """Send one alert to an external destination."""


@dataclass(slots=True, frozen=True, kw_only=True)
class NoOpAlertNotifier:
    """Alert notifier that intentionally drops all notifications."""

    def notify(self, alert: AlertNotification) -> None:
        del alert


@dataclass(slots=True, kw_only=True)
class RecordingAlertNotifier:
    """In-memory notifier used by tests."""

    notifications: list[AlertNotification] = field(default_factory=list)

    def notify(self, alert: AlertNotification) -> None:
        self.notifications.append(alert)


@dataclass(slots=True, frozen=True, kw_only=True)
class WebhookAlertNotifier:
    """Post operational alerts to a webhook endpoint."""

    webhook_url: str
    timeout_seconds: int = 5
    session: requests.Session | None = None

    def notify(self, alert: AlertNotification) -> None:
        session = self.session or requests.Session()
        response = session.post(
            self.webhook_url,
            json={
                "alert_id": alert.alert_id,
                "timestamp": alert.timestamp.isoformat(),
                "severity": alert.severity,
                "code": alert.code,
                "title": alert.title,
                "message": alert.message,
                "metadata": alert.metadata,
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                "Webhook alert delivery failed. "
                f"status_code={response.status_code}, body={response.text}"
            )


@dataclass(slots=True, kw_only=True)
class AlertDispatcher:
    """Dispatch one or more alerts to registered notifiers."""

    notifiers: Sequence[AlertNotifier] = field(default_factory=tuple)

    def dispatch(self, alert: AlertNotification) -> None:
        """Dispatch one alert without failing the caller on notifier errors."""

        for notifier in self.notifiers:
            try:
                notifier.notify(alert)
            except Exception:
                continue

    def dispatch_all(self, alerts: Sequence[AlertNotification]) -> None:
        """Dispatch multiple alerts in order."""

        for alert in alerts:
            self.dispatch(alert)
