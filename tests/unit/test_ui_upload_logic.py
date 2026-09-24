from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.ui.errors import ApiError, ApiUnavailableError
from src.ui.models import InvoiceData, InvoiceView
from src.ui.upload_logic import MAX_BYTES, MAX_FILES, Candidate, precheck, process_batch

PDF = b"%PDF-1.4 something"
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _view(name: str = "f.pdf") -> InvoiceView:
    return InvoiceView(
        id="3f9a1c2e-7b4d-4e8a-9c31-5d2f0a6b8e14",
        created_at=NOW,
        expires_at=NOW + timedelta(days=30),
        display_name=name,
        status="high",
        invoice=InvoiceData(supplier="Orange SA", total_ttc=120.0),
    )


class FakeClient:
    """Answers each file in turn: an InvoiceView, or raises the given error."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.sent: list[str] = []
        self.sent_mimes: list[str] = []

    def upload(self, filename: str, data: bytes, mime: str) -> InvoiceView:
        self.sent.append(filename)
        self.sent_mimes.append(mime)
        answer = self.answers.pop(0) if self.answers else _view(filename)
        if isinstance(answer, Exception):
            raise answer
        return answer


# --- what is not even sent ---
@pytest.mark.parametrize(
    ("data", "reason"),
    [
        pytest.param(b"", "vide", id="empty"),
        pytest.param(b"MZ\x90\x00", "non reconnu", id="executable"),
        # the signature must be the first bytes
        pytest.param(b"junk%PDF-1.4", "non reconnu", id="signature-not-first"),
        # explicit ids: pytest would otherwise build a test name out of these 10 MB of bytes,
        # which Windows refuses to store in an environment variable (32,767 characters max)
        pytest.param(b"%PDF" + b"0" * MAX_BYTES, "volumineux", id="too-big"),
    ],
)
def test_precheck_skips_files_the_server_would_refuse(data: bytes, reason: str) -> None:
    assert reason in (precheck(Candidate("x.pdf", data)) or "")


def test_a_valid_pdf_passes_the_precheck() -> None:
    assert precheck(Candidate("x.pdf", PDF)) is None
    assert precheck(Candidate("x.pdf", b"%PDF-" + b"0" * (MAX_BYTES - 5))) is None  # at the limit


def test_skipped_files_cost_no_request_and_do_not_stop_the_batch() -> None:
    client = FakeClient()
    outcomes = process_batch(
        client,
        [Candidate("a.pdf", PDF), Candidate("empty.pdf", b""), Candidate("b.pdf", PDF)],
    )
    assert [o.kind for o in outcomes] == ["ok", "skipped", "ok"]
    assert client.sent == ["a.pdf", "b.pdf"]
    assert "vide" in outcomes[1].message and outcomes[1].message.startswith("Ignoré")


# --- errors: which ones stop the batch ---
@pytest.mark.parametrize("status", [400, 413, 415, 422, 502])
def test_a_problem_with_one_document_does_not_stop_the_others(status: int) -> None:
    client = FakeClient(ApiError(status, "Ce document pose problème."))
    outcomes = process_batch(client, [Candidate("a.pdf", PDF), Candidate("b.pdf", PDF)])
    assert [o.kind for o in outcomes] == ["error", "ok"]
    assert outcomes[0].message == "Ce document pose problème." and client.sent == ["a.pdf", "b.pdf"]


@pytest.mark.parametrize("status", [401, 429, 500, 503, 504])
def test_an_error_that_would_hit_every_file_stops_the_batch(status: int) -> None:
    client = FakeClient(ApiError(status, "Trop de requêtes.", retry_after=42))
    outcomes = process_batch(
        client, [Candidate("a.pdf", PDF), Candidate("b.pdf", PDF), Candidate("c.pdf", PDF)]
    )
    assert [o.kind for o in outcomes] == ["error", "not_run", "not_run"]
    assert client.sent == ["a.pdf"]  # the rest was never sent: no wasted quota
    assert outcomes[0].retry_after == 42
    assert "Non traité : Trop de requêtes." == outcomes[1].message


def test_an_unreachable_api_stops_the_batch() -> None:
    client = FakeClient(ApiUnavailableError("API injoignable."))
    outcomes = process_batch(client, [Candidate("a.pdf", PDF), Candidate("b.pdf", PDF)])
    assert [o.kind for o in outcomes] == ["error", "not_run"] and client.sent == ["a.pdf"]


def test_a_programming_error_is_not_swallowed() -> None:
    client = FakeClient(RuntimeError("bug"))
    with pytest.raises(RuntimeError):
        process_batch(client, [Candidate("a.pdf", PDF)])


# --- limits and order ---
def test_files_beyond_the_batch_limit_are_reported_and_never_sent() -> None:
    client = FakeClient()
    candidates = [Candidate(f"f{i}.pdf", PDF) for i in range(MAX_FILES + 3)]
    outcomes = process_batch(client, candidates)
    assert len(outcomes) == MAX_FILES + 3 and len(client.sent) == MAX_FILES
    assert [o.kind for o in outcomes[MAX_FILES:]] == ["not_run"] * 3
    assert f"{MAX_FILES} fichiers maximum" in outcomes[-1].message


def test_files_are_sent_one_at_a_time_in_order_with_progress() -> None:
    client = FakeClient()
    calls: list[tuple[int, int, str]] = []
    process_batch(
        client,
        [Candidate("a.pdf", PDF), Candidate("bad.pdf", b""), Candidate("c.pdf", PDF)],
        progress=lambda done, total, name: calls.append((done, total, name)),
    )
    assert client.sent == ["a.pdf", "c.pdf"]
    assert calls == [(0, 3, "a.pdf"), (2, 3, "c.pdf")]  # skipped files are not announced


def test_hostile_file_names_pass_through_untouched_as_data() -> None:
    hostile = "![x](http://evil.example/?d=1)<script>.pdf"
    outcomes = process_batch(FakeClient(), [Candidate(hostile, PDF)])
    assert outcomes[0].name == hostile and outcomes[0].kind == "ok"  # escaping is the page's job


def test_an_empty_selection_gives_no_outcome() -> None:
    assert process_batch(FakeClient(), []) == []


# --- photos / scans ------------------------------------------------------------------------
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF something"
PNG = b"\x89PNG\r\n\x1a\n something"


@pytest.mark.parametrize("data", [JPEG, PNG])
def test_a_valid_photo_passes_the_precheck(data: bytes) -> None:
    assert precheck(Candidate("x.jpg", data)) is None


def test_process_batch_sends_the_detected_mime_for_each_file() -> None:
    client = FakeClient()
    process_batch(
        client, [Candidate("a.pdf", PDF), Candidate("b.jpg", JPEG), Candidate("c.png", PNG)]
    )
    assert client.sent_mimes == ["application/pdf", "image/jpeg", "image/png"]
