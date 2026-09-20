from __future__ import annotations

import time
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from src.core.env import get_int_env
from src.core.exceptions import PDFCorruptedError, PDFTooLargeError
from src.ocr import extractor
from tests.unit import _isolated_targets as targets


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


def test_hanging_parser_is_killed_after_timeout() -> None:
    started = time.monotonic()
    with pytest.raises(PDFTooLargeError, match="exceeded"):
        extractor._run_isolated(targets.sleep_forever, (), timeout=1)
    assert time.monotonic() - started < 15  # killed, we did not wait the 60 s of the target


def test_crashing_parser_process_is_reported_as_corrupted() -> None:
    with pytest.raises(PDFCorruptedError, match="crashed"):
        extractor._run_isolated(targets.hard_crash, (), timeout=15)


def test_exception_in_child_is_reported_as_corrupted() -> None:
    assert extractor._run_isolated(targets.raise_error, (), timeout=15) == ("corrupted",)


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


def test_child_main_always_answers() -> None:
    class _Conn:
        sent: list = []
        closed = False

        def send(self, value):
            self.sent.append(value)

        def close(self):
            self.closed = True

    conn = _Conn()
    extractor._child_main(conn, targets.raise_error, ())
    assert conn.sent == [("corrupted",)] and conn.closed
