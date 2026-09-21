from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from src.core.env import get_int_env
from src.core.exceptions import PDFCorruptedError, PDFTooLargeError
from src.ocr import extractor


def _make_pdf(path: Path, pages: int, line: str = "FACTURE test ligne de texte") -> Path:
    pdf = canvas.Canvas(str(path))
    for _ in range(pages):
        pdf.drawString(72, 750, line)
        pdf.showPage()
    pdf.save()
    return path


def test_too_many_pages_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "5")
    with pytest.raises(PDFTooLargeError, match="pages"):
        extractor.extract_text_from_pdf(_make_pdf(tmp_path / "many.pdf", pages=6))


def test_page_count_at_the_limit_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "5")
    result = extractor.extract_text_from_pdf(_make_pdf(tmp_path / "five.pdf", pages=5))
    assert result.page_count == 5


def test_too_much_text_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_PDF_TEXT_CHARS", "100")
    with pytest.raises(PDFTooLargeError, match="characters"):
        extractor.extract_text_from_pdf(_make_pdf(tmp_path / "text.pdf", pages=10))


def test_file_too_big_rejected_before_any_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.4\n" + b"0" * (2 * 1024 * 1024))
    started = time.monotonic()
    with pytest.raises(PDFTooLargeError, match="MB"):
        extractor.extract_text_from_pdf(big)
    assert time.monotonic() - started < 1  # rejected on file size alone, no process spawned


def test_file_without_pdf_header_rejected(tmp_path: Path) -> None:
    fake = tmp_path / "evil.pdf"
    fake.write_bytes(b"MZ\x90\x00 this is an executable, not a PDF")
    with pytest.raises(PDFCorruptedError, match="header"):
        extractor.extract_text_from_pdf(fake)


_TARGETS = "tests.unit._isolated_targets"


def test_hanging_parser_is_killed_after_timeout() -> None:
    started = time.monotonic()
    with pytest.raises(PDFTooLargeError, match="exceeded"):
        extractor._run_isolated(_TARGETS, ["sleep"], timeout=1)
    assert time.monotonic() - started < 15  # killed, we did not wait the 60 s of the worker


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("crash", "crashed"),  # non-zero exit without an answer
        ("raise", "crashed"),
        ("garbage", "no valid answer"),
        ("empty-list", "no valid answer"),
        ("huge", "too much data"),
    ],
)
def test_a_misbehaving_worker_is_reported_as_a_corrupted_pdf(mode: str, message: str) -> None:
    with pytest.raises(PDFCorruptedError, match=message):
        extractor._run_isolated(_TARGETS, [mode], timeout=30)


def test_a_well_behaved_worker_answers_through_json() -> None:
    assert extractor._run_isolated(_TARGETS, ["ok"], timeout=30) == ("ok",)


def test_the_parser_process_does_not_inherit_the_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """A process that parses hostile files has no use for the Gemini / encryption keys."""
    for key in ("GOOGLE_API_KEY", "CACHE_ENCRYPTION_KEY", "API_TOKEN"):
        monkeypatch.setenv(key, f"SECRET-{key}")
    status, seen = extractor._run_isolated(_TARGETS, ["env"], timeout=30)
    assert status == "ok"
    assert seen == {"GOOGLE_API_KEY": None, "CACHE_ENCRYPTION_KEY": None, "API_TOKEN": None}


def test_the_extraction_works_even_when_the_callers_main_module_is_hijacked(
    tmp_path: Path, sample_invoice_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression. The first design used multiprocessing "spawn", which re-imports the parent's
    `__main__` in the child. Streamlit (and test runners, notebooks) replace `__main__` with
    their own script: the child re-ran THAT script instead of parsing, and the parent waited
    for the full timeout. The worker is now an independent command."""
    hijacker = tmp_path / "some_streamlit_page.py"
    hijacker.write_text("raise SystemExit('this script must never be re-run by the parser')\n")
    fake_main = types.ModuleType("__main__")
    fake_main.__file__ = str(hijacker)
    monkeypatch.setitem(sys.modules, "__main__", fake_main)

    started = time.monotonic()
    result = extractor.extract_text_from_pdf(sample_invoice_pdf)
    assert "FACTURE" in result.text and time.monotonic() - started < 15


def test_the_isolation_no_longer_depends_on_multiprocessing() -> None:
    source = Path(extractor.__file__).read_text(encoding="utf-8")
    # (the docstring explains why it is not used: look at the imports, not the word)
    assert "import multiprocessing" not in source and "from multiprocessing" not in source


def test_metadata_sent_back_by_the_worker_is_bounded(tmp_path: Path) -> None:
    """A hostile PDF can carry enormous metadata: it must not travel through the pipe."""
    pdf = _make_pdf(tmp_path / "meta.pdf", pages=1)
    status, _pages, _count, metadata = extractor._read_pdf(str(pdf), 30, 100_000)
    assert status == "ok" and len(metadata) <= 100
    assert all(len(key) <= 1000 and len(value) <= 1000 for key, value in metadata.items())


@pytest.mark.parametrize("raw", ["abc", "0", "-5", ""])
def test_invalid_limit_settings_fall_back_to_default(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo in a limit must never disable the limit."""
    monkeypatch.setenv("MAX_PDF_PAGES", raw)
    assert get_int_env("MAX_PDF_PAGES", 30) == 30


# `_read_pdf` normally runs in the child process, which coverage cannot see: call it directly.
def test_read_pdf_returns_pages_and_metadata(sample_invoice_pdf: Path) -> None:
    status, pages, count, metadata = extractor._read_pdf(str(sample_invoice_pdf), 30, 100_000)
    assert status == "ok" and count == 1 and "FACTURE" in pages[0]
    assert isinstance(metadata, dict)


def test_read_pdf_reports_limits_and_corruption(tmp_path: Path, sample_invoice_pdf: Path) -> None:
    assert extractor._read_pdf(str(sample_invoice_pdf), 0, 100_000)[0] == "too_large"
    assert extractor._read_pdf(str(sample_invoice_pdf), 30, 5)[0] == "too_large"
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 truncated")
    assert extractor._read_pdf(str(broken), 30, 100_000) == ("corrupted",)


def test_the_worker_prints_its_answer_as_json(
    sample_invoice_pdf: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Direct call: the worker normally runs in a child process that coverage cannot see."""
    import json

    from src.ocr import worker

    assert worker.main(["worker", str(sample_invoice_pdf), "30", "100000"]) == 0
    status, pages, count, metadata = json.loads(capsys.readouterr().out)
    assert status == "ok" and count == 1 and "FACTURE" in pages[0] and isinstance(metadata, dict)
