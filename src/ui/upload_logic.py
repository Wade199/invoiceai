from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from src.ui.errors import ApiError, ApiUnavailableError, UiError
from src.ui.models import InvoiceView

MAX_FILES = 10  # per batch: the free Gemini tier allows 20 extractions a day anyway
MAX_BYTES = 10 * 1024 * 1024  # same limit as the API; the server stays the judge
# Same magic numbers as src/api/upload.py — kept separate on purpose (the UI never imports
# from src.api): a mismatch here only means a slightly wrong pre-check message, the server
# re-validates every upload regardless.
_TYPE_MAGIC: dict[str, bytes] = {
    "application/pdf": b"%PDF-",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}
_SERVER_SIDE_DOCUMENT_ERROR = 502  # "extraction failed for THIS document": the next may work

Kind = Literal["ok", "skipped", "error", "not_run"]


class _Uploader(Protocol):
    def upload(self, filename: str, data: bytes, mime: str) -> InvoiceView: ...


def sniff_mime(data: bytes) -> str | None:
    """Guess the content type from the file's own first bytes; `None` if none match.

    Only used to skip an obviously-wrong file before spending a request and to pick the
    `Content-Type` sent to the API — the server is the one that actually decides (same magic
    numbers, checked again server-side; see src/api/upload.py).
    """
    for mime, magic in _TYPE_MAGIC.items():
        if data.startswith(magic):
            return mime
    return None


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
    if sniff_mime(candidate.data) is None:
        return "format non reconnu (PDF, JPG ou PNG uniquement)"
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
            # precheck() already confirmed this is not None.
            mime = sniff_mime(candidate.data) or "application/pdf"
            record = client.upload(candidate.name, candidate.data, mime)
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
