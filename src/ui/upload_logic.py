from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from src.ui.errors import ApiError, ApiUnavailableError, UiError
from src.ui.models import InvoiceView

MAX_FILES = 10  # per batch: the free Gemini tier allows 20 extractions a day anyway
MAX_BYTES = 10 * 1024 * 1024  # same limit as the API; the server stays the judge
_PDF_MAGIC = b"%PDF-"
_SERVER_SIDE_DOCUMENT_ERROR = 502  # "extraction failed for THIS document": the next may work

Kind = Literal["ok", "skipped", "error", "not_run"]


class _Uploader(Protocol):
    def upload(self, filename: str, data: bytes) -> InvoiceView: ...


@dataclass(frozen=True)
class Candidate:
    name: str
    data: bytes


@dataclass(frozen=True)
class Outcome:
    """What happened to one file. `message` is safe text from us or from the API."""

    name: str
    kind: Kind
    message: str = ""
    record: InvoiceView | None = None
    retry_after: int | None = None


def precheck(candidate: Candidate) -> str | None:
    """Reasons to skip a file without spending a request. The server checks again."""
    if not candidate.data:
        return "fichier vide"
    if len(candidate.data) > MAX_BYTES:
        return "fichier trop volumineux (10 Mo maximum)"
    if not candidate.data.startswith(_PDF_MAGIC):
        return "ce n'est pas un PDF valide"
    return None


def _stops_the_batch(error: UiError) -> bool:
    """True when the next files would fail for the same reason (or waste quota).

    Not a problem with one document: API unreachable, bad token, rate limit / quota (429),
    server errors. A 4xx about this file, or 502 (this document could not be extracted),
    only concerns that file.
    """
    if isinstance(error, ApiUnavailableError):
        return True
    if isinstance(error, ApiError):
        return (
            error.status in (401, 429)
            or error.status >= 500
            and error.status != _SERVER_SIDE_DOCUMENT_ERROR
        )
    return False


def process_batch(
    client: _Uploader,
    candidates: Sequence[Candidate],
    progress: Callable[[int, int, str], None] | None = None,
) -> list[Outcome]:
    """Extract the files one after the other (never in parallel: quota and server limits).

    Returns one outcome per candidate, in order. After an error that would hit every
    following file, those are reported as "not run" instead of being sent.
    """
    batch, extra = list(candidates[:MAX_FILES]), list(candidates[MAX_FILES:])
    outcomes: list[Outcome] = []
    stop_reason: str | None = None

    for index, candidate in enumerate(batch):
        if stop_reason is not None:
            outcomes.append(Outcome(candidate.name, "not_run", f"Non traité : {stop_reason}"))
            continue
        problem = precheck(candidate)
        if problem:
            outcomes.append(Outcome(candidate.name, "skipped", f"Ignoré : {problem}."))
            continue
        if progress:
            progress(index, len(batch), candidate.name)
        try:
            record = client.upload(candidate.name, candidate.data)
        except UiError as error:
            retry_after = getattr(error, "retry_after", None)
            outcomes.append(Outcome(candidate.name, "error", str(error), retry_after=retry_after))
            if _stops_the_batch(error):
                stop_reason = str(error)
            continue
        outcomes.append(Outcome(candidate.name, "ok", record=record))

    for candidate in extra:
        outcomes.append(
            Outcome(
                candidate.name, "not_run", f"Non traité : {MAX_FILES} fichiers maximum par lot."
            )
        )
    return outcomes
