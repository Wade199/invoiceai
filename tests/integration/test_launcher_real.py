"""Really start `scripts/run.py`: both servers answer, then both stop when asked."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "l" * 43


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _up(port: int, path: str) -> bool:
    try:
        return (
            httpx.get(f"http://127.0.0.1:{port}{path}", timeout=2, trust_env=False).status_code
            == 200
        )
    except httpx.HTTPError:
        return False


def _down(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def test_one_command_starts_both_servers_and_stops_both(tmp_path: Path) -> None:
    api_port, ui_port = _free_port(), _free_port()
    env = {
        **os.environ,
        "GOOGLE_API_KEY": "AQ.fake-key-never-used",
        "CACHE_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "API_TOKEN": TOKEN,
        "DATABASE_URL": f"sqlite:///{(tmp_path / 't.db').as_posix()}",
        "CACHE_DIR": str(tmp_path / "cache"),
        "UPLOAD_DIR": str(tmp_path / "uploads"),
    }
    process = subprocess.Popen(
        [sys.executable, "scripts/run.py", "--no-browser",
         "--api-port", str(api_port), "--ui-port", str(ui_port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )  # fmt: skip
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and not (
            _up(api_port, "/health") and _up(ui_port, "/_stcore/health")
        ):
            assert process.poll() is None, "the launcher exited early"
            time.sleep(0.5)
        assert _up(api_port, "/health"), "API did not start"
        assert _up(ui_port, "/_stcore/health"), "interface did not start"
        # the API is protected, and only the launcher's own port is open to it
        assert (
            httpx.get(f"http://127.0.0.1:{api_port}/invoices", trust_env=False).status_code == 401
        )
    finally:
        process.terminate()  # what Ctrl+C / closing the terminal does to the launcher
        try:
            process.wait(30)
        except subprocess.TimeoutExpired:
            process.kill()

    for _ in range(50):  # children must be gone too, not orphaned
        if _down(api_port) and _down(ui_port):
            break
        time.sleep(0.3)
    assert _down(api_port), "the API keeps running after the launcher stopped"
    assert _down(ui_port), "the interface keeps running after the launcher stopped"
