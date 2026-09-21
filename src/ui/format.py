from __future__ import annotations

from datetime import UTC, datetime

_STATUS = {"high": "✅ Fiable", "low": "⚠️ À vérifier"}


def euro(value: float | None) -> str:
    """`1 234,56 €`: French format (space thousands separator, decimal comma)."""
    if value is None:
        return "—"
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " €"


def percent(rate: float | None) -> str:
    """A rate stored as a fraction (0.2) or already as a percentage (20) reads `20 %`."""
    if rate is None:
        return "—"
    number = rate * 100 if rate <= 1 else rate
    return f"{number:g}".replace(".", ",") + " %"


def status_label(status: str) -> str:
    return _STATUS.get(status, status)


def day(moment: datetime) -> str:
    return moment.astimezone().strftime("%d/%m/%Y")


def days_left(expires_at: datetime, now: datetime | None = None) -> int:
    """Whole days before automatic deletion (0 when it is due today or overdue)."""
    remaining = expires_at - (now or datetime.now(UTC))
    return max(0, remaining.days)
