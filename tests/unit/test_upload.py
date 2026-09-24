from __future__ import annotations

import asyncio
import io
import os
import re
import time
from pathlib import Path

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from src.api import upload
from src.core.exceptions import InvalidUploadError, StorageError, UploadTooLargeError

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


def _file(data: bytes, filename: str | None = "facture.pdf", mime: str | None = "application/pdf"):
    headers = Headers({"content-type": mime}) if mime else Headers({})
    return UploadFile(io.BytesIO(data), filename=filename, headers=headers)


def _save(data: bytes, **kwargs):
    return asyncio.run(upload.save_upload(_file(data, **kwargs)))


def _files_in(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


# --- happy path ---------------------------------------------------------------------------
def test_valid_pdf_is_stored_under_a_server_generated_name(upload_dir: Path) -> None:
    stored = _save(PDF)
    assert stored.path.parent == upload_dir
    assert re.fullmatch(r"[0-9a-f]{32}\.pdf", stored.path.name)
    assert stored.path.read_bytes() == PDF
    assert stored.size == len(PDF)
    assert stored.display_name == "facture.pdf"


def test_two_uploads_never_share_a_name() -> None:
    assert _save(PDF).path != _save(PDF).path


def test_client_file_name_is_never_used_as_a_path(upload_dir: Path, tmp_path: Path) -> None:
    stored = _save(PDF, filename="../../evil.pdf")
    assert stored.path.parent == upload_dir
    assert stored.display_name == "evil.pdf"
    assert not (tmp_path / "evil.pdf").exists()


def test_mime_type_parameters_are_accepted() -> None:
    assert _save(PDF, mime="Application/PDF; charset=binary").size == len(PDF)


# --- photos / scans (Gemini multimodal path, see gemini_adapter.py) -----------------------
def test_valid_jpeg_is_stored_with_a_jpg_extension(upload_dir: Path) -> None:
    stored = _save(JPEG, filename="photo.jpg", mime="image/jpeg")
    assert re.fullmatch(r"[0-9a-f]{32}\.jpg", stored.path.name)
    assert stored.mime == "image/jpeg"
    assert stored.path.read_bytes() == JPEG


def test_valid_png_is_stored_with_a_png_extension(upload_dir: Path) -> None:
    stored = _save(PNG, filename="scan.png", mime="image/png")
    assert re.fullmatch(r"[0-9a-f]{32}\.png", stored.path.name)
    assert stored.mime == "image/png"


def test_pdf_upload_still_reports_its_mime() -> None:
    assert _save(PDF).mime == "application/pdf"


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (PDF, "image/jpeg"),  # right bytes for a PDF, declared as an image
        (JPEG, "image/png"),  # a JPEG declared as a PNG
        (PNG, "image/jpeg"),  # a PNG declared as a JPEG
        (b"not an image at all", "image/jpeg"),
        (b"not an image at all", "image/png"),
    ],
)
def test_image_content_must_match_its_declared_type(
    data: bytes, mime: str, upload_dir: Path
) -> None:
    with pytest.raises(InvalidUploadError):
        _save(data, mime=mime)
    assert _files_in(upload_dir) == []


def test_file_exactly_at_the_size_limit_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")
    data = PDF + b"0" * (1024 * 1024 - len(PDF))
    assert _save(data).size == 1024 * 1024


# --- rejections (and nothing left on disk) --------------------------------------------------
@pytest.mark.parametrize(
    "mime", ["text/html", "application/x-msdownload", "image/webp", "image/gif", "", None]
)
def test_wrong_mime_type_is_rejected(mime: str | None, upload_dir: Path) -> None:
    with pytest.raises(InvalidUploadError):
        _save(PDF, mime=mime)
    assert _files_in(upload_dir) == []


@pytest.mark.parametrize(
    "data",
    [
        b"MZ\x90\x00 this is an executable",
        b"<html><script>alert(1)</script></html>",
        b"junk%PDF-1.4 header not at offset 0",
        b"%PDF",  # too short to be a header
    ],
)
def test_right_mime_but_not_a_pdf_is_rejected(data: bytes, upload_dir: Path) -> None:
    with pytest.raises(InvalidUploadError):
        _save(data)
    assert _files_in(upload_dir) == []


def test_empty_file_is_rejected(upload_dir: Path) -> None:
    with pytest.raises(InvalidUploadError):
        _save(b"")
    assert _files_in(upload_dir) == []


def test_oversize_file_is_rejected_and_partial_file_removed(
    monkeypatch: pytest.MonkeyPatch, upload_dir: Path
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")
    with pytest.raises(UploadTooLargeError):
        _save(PDF + b"0" * (1024 * 1024 + 1))
    assert _files_in(upload_dir) == []


def test_unwritable_upload_dir_raises_storage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    monkeypatch.setenv("UPLOAD_DIR", str(blocker))
    with pytest.raises(StorageError):
        _save(PDF)


# --- display_name -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "document.pdf"),
        ("", "document.pdf"),
        ("facture.pdf", "facture.pdf"),
        ("a/b/c.pdf", "c.pdf"),
        (r"C:\Users\ibrahima\Desktop\facture 1.pdf", "facture 1.pdf"),
        ("../../../etc/passwd", "passwd"),
        ("///", "document.pdf"),
        ("fact\x00ure\r\n.pdf", "fact ure .pdf"),
        ("evil\u202egnp.exe", "evil gnp.exe"),
    ],
)
def test_display_name_is_a_safe_label(raw: str | None, expected: str) -> None:
    assert upload.display_name(raw) == expected


def test_display_name_is_length_capped() -> None:
    assert len(upload.display_name("x" * 1000 + ".pdf")) == 100


# --- deletion ------------------------------------------------------------------------------------
def test_delete_upload_removes_the_file_and_tolerates_a_missing_one() -> None:
    stored = _save(PDF)
    upload.delete_upload(stored.path)
    assert not stored.path.exists()
    upload.delete_upload(stored.path)  # already gone: no error


def test_delete_upload_refuses_files_outside_the_upload_dir(tmp_path: Path) -> None:
    outsider = tmp_path / "precious.txt"
    outsider.write_text("do not delete")
    upload.delete_upload(outsider)
    assert outsider.exists()


def test_purge_stale_uploads_removes_only_old_files(upload_dir: Path) -> None:
    old, fresh = _save(PDF).path, _save(PDF).path
    two_hours_ago = time.time() - 7_200
    os.utime(old, (two_hours_ago, two_hours_ago))
    assert upload.purge_stale_uploads() == 1
    assert not old.exists() and fresh.exists()


def test_purge_on_missing_directory_is_a_noop() -> None:
    assert upload.purge_stale_uploads() == 0
