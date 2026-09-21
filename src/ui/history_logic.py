from __future__ import annotations

from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import pandas as pd

from src.ui.errors import ApiError, ApiUnavailableError, UiError
from src.ui.format import day, euro, status_label
from src.ui.models import SummaryView

CURRENT_RECORD_KEY = "current_record_id"  # same session key as the Result page
MAX_ROWS = 500  # the API's own cap for a list
DASH = "—"
# What the user picks -> what the API expects.
STATUS_CHOICES: dict[str, Literal["high", "low"] | None] = {
    "Toutes": None,
    "✅ Fiables": "high",
    "⚠️ À vérifier": "low",
}
COLUMNS = ["Date", "Fournisseur", "N° facture", "Total TTC", "Fiabilité", "Fichier", "Traité le"]


def to_frame(rows: Sequence[SummaryView]) -> pd.DataFrame:
    """The table shown on screen. Every cell is plain text: a dataframe shows it literally,
    so a hostile supplier or file name never becomes markup."""
    return pd.DataFrame(
        [
            {
                "Date": row.date or DASH,
                "Fournisseur": row.supplier or DASH,
                "N° facture": row.invoice_number or DASH,
                "Total TTC": euro(row.total_ttc),
                "Fiabilité": status_label(row.status),
                "Fichier": row.display_name,
                "Traité le": day(row.created_at),
            }
            for row in rows
        ],
        columns=COLUMNS,
    )


def ids_for_selection(rows: Sequence[SummaryView], positions: Sequence[int]) -> list[str]:
    """Ids of the selected table rows. Out-of-range positions are ignored, never an error."""
    return [rows[position].id for position in positions if 0 <= position < len(rows)]


def limit_reached(count: int) -> bool:
    return count >= MAX_ROWS


class _Deleter(Protocol):
    def delete(self, record_id: str) -> None: ...


@dataclass
class DeleteReport:
    deleted: int = 0
    already_gone: int = 0  # expired or deleted elsewhere in the meantime: the goal is reached
    failed: list[str] = field(default_factory=list)  # one message per invoice that could not go
    not_attempted: int = 0  # left alone because an error would have hit every one of them

    @property
    def summary(self) -> str:
        parts = [f"{self.deleted} facture(s) supprimée(s)"]
        if self.already_gone:
            parts.append(f"{self.already_gone} déjà absente(s)")
        if self.failed:
            parts.append(f"{len(self.failed)} échec(s)")
        if self.not_attempted:
            parts.append(f"{self.not_attempted} non traitée(s)")
        return " · ".join(parts) + "."


def _stops_the_batch(error: UiError) -> bool:
    if isinstance(error, ApiUnavailableError):
        return True
    return isinstance(error, ApiError) and (error.status in (401, 429) or error.status >= 500)


def delete_many(
    client: _Deleter, ids: Sequence[str], state: MutableMapping[str, Any] | None = None
) -> DeleteReport:
    """Erase several invoices (record, cache entry, data in the file), one by one.

    A 404 counts as done (already gone). An error that would hit every invoice (bad token,
    API down, rate limit, server error) stops the run; the rest is reported as not attempted.
    If the invoice shown on the Result page is erased, it is forgotten in the session.
    """
    report = DeleteReport()
    for position, record_id in enumerate(ids):
        try:
            client.delete(record_id)
        except ApiError as error:
            if error.status == 404:
                report.already_gone += 1
            else:
                report.failed.append(str(error))
                if _stops_the_batch(error):
                    report.not_attempted = len(ids) - position - 1
                    break
                continue
        except UiError as error:  # API unreachable
            report.failed.append(str(error))
            report.not_attempted = len(ids) - position - 1
            break
        else:
            report.deleted += 1
        if state is not None and state.get(CURRENT_RECORD_KEY) == record_id:
            state.pop(CURRENT_RECORD_KEY, None)
    return report
