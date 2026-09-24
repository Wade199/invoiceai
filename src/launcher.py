from __future__ import annotations

import argparse
import os
import socket

# The launcher runs two fixed commands (uvicorn, streamlit), never through a shell.
import subprocess  # nosec B404
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx
from cryptography.fernet import Fernet
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"  # both servers listen on the local machine only (V1 = one local user)
DEFAULT_API_PORT = 8000
DEFAULT_UI_PORT = 8501
_REQUIRED = ("GOOGLE_API_KEY", "CACHE_ENCRYPTION_KEY", "API_TOKEN")
_MIN_TOKEN_LENGTH = 32
_API_START_TIMEOUT = 40.0
_STOP_TIMEOUT = 10.0


def check_environment(root: Path, environ: Mapping[str, str] | None = None) -> list[str]:
    """Return what is wrong with the configuration, in French. Never returns a secret value.

    Values come from the real environment first, then from `.env`. Only *presence and shape*
    are checked here: the file is read to inspect, not loaded into this process.
    """
    environ = os.environ if environ is None else environ
    file_values = dotenv_values(root / ".env") if (root / ".env").is_file() else {}
    values = {key: environ.get(key) or file_values.get(key) or "" for key in _REQUIRED}

    problems = []
    for key in _REQUIRED:
        if not values[key]:
            problems.append(f"{key} est absente (voir .env.example).")
    if values["API_TOKEN"] and len(values["API_TOKEN"]) < _MIN_TOKEN_LENGTH:
        problems.append(
            f"API_TOKEN est trop courte (minimum {_MIN_TOKEN_LENGTH} caractères) : "
            "python scripts/generate_api_token.py"
        )
    if values["CACHE_ENCRYPTION_KEY"]:
        try:
            Fernet(values["CACHE_ENCRYPTION_KEY"].encode())
        except (ValueError, TypeError):
            problems.append(
                "CACHE_ENCRYPTION_KEY n'est pas une clé valide : "
                "python scripts/generate_cache_key.py"
            )
    return problems


def port_is_free(port: int, host: str = HOST) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) != 0


def build_commands(
    python: str, api_port: int, ui_port: int, *, headless: bool, ui_host: str = HOST
) -> tuple[list[str], list[str]]:
    """The two commands: the API (uvicorn, factory mode) and the interface (Streamlit).

    The API always binds `HOST` (127.0.0.1): nothing outside this machine's own processes
    should ever reach it directly. `ui_host` defaults to the same loopback-only address for a
    native run, but can be widened (e.g. "0.0.0.0" in Docker, see UI_HOST in main()) since a
    container's 127.0.0.1 is only reachable from inside that same container — the UI itself
    still only talks to the API over the container's own loopback either way.
    """
    api = [
        python, "-m", "uvicorn", "src.api.app:create_app", "--factory",
        "--host", HOST, "--port", str(api_port),
        # searches travel in the URL (?q=Orange): the access log would record them
        "--no-access-log", "--no-server-header",
    ]  # fmt: skip
    ui = [
        python, "-m", "streamlit", "run", "src/ui/app.py",
        "--server.address", ui_host, "--server.port", str(ui_port),
        "--server.headless", "true" if headless else "false",
    ]  # fmt: skip
    return api, ui


def wait_until_healthy(url: str, timeout: float, alive) -> bool:
    """Poll `url` until it answers 200, the timeout expires, or `alive()` turns False."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and alive():
        try:
            if httpx.get(url, timeout=2.0, trust_env=False).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.4)
    return False


class ProcessGuard:
    """Make the child servers die with the launcher, even if the launcher is killed.

    Closing the terminal or `taskkill` end the launcher without running its cleanup code, and
    the API (which holds the Gemini and encryption keys in memory) would keep running with
    nobody aware of it. Windows: the children are put in a Job Object flagged
    "kill on close" (the kernel ends them when the launcher's handle disappears). Linux: each
    child asks to receive SIGTERM when its parent dies. Elsewhere (macOS) there is no
    equivalent: normal exits and Ctrl+C are still cleaned up by `main`.
    """

    def __init__(self) -> None:
        self._job = _create_kill_on_close_job() if sys.platform == "win32" else None

    def popen(self, command: list[str], **kwargs) -> subprocess.Popen:
        if sys.platform.startswith("linux"):  # pragma: no cover - not exercised on Windows
            kwargs["preexec_fn"] = _die_with_parent
        # The argument list is built from constants, integers and sys.executable: no shell
        # and no user-controlled string ever reaches it.
        process = subprocess.Popen(command, **kwargs)  # nosec B603
        if self._job is not None:
            _assign_to_job(self._job, process)
        return process


def _die_with_parent() -> None:  # pragma: no cover - Linux only
    import ctypes
    import signal

    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


def _create_kill_on_close_job():  # pragma: no cover - Windows only, exercised by the real test
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )
        ]  # fmt: skip

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]  # fmt: skip
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
    return job if ok else None


def _assign_to_job(job, process: subprocess.Popen) -> None:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    if not kernel32.AssignProcessToJobObject(job, int(process._handle)):
        print("Avertissement : le serveur ne sera pas arrêté automatiquement si ce script est tué.")


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(_STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(5)


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Start the InvoiceAI API and interface.")
    parser.add_argument("--api-port", type=int, default=DEFAULT_API_PORT)
    parser.add_argument("--ui-port", type=int, default=DEFAULT_UI_PORT)
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args(argv)

    problems = check_environment(root)
    for port, label in ((args.api_port, "de l'API"), (args.ui_port, "de l'interface")):
        if not port_is_free(port):
            problems.append(f"Le port {port} {label} est déjà utilisé (--api-port / --ui-port).")
    if problems:
        print("Impossible de démarrer :")
        for problem in problems:
            print(f"  - {problem}")
        return 2

    # Not exposed as a CLI flag on purpose: this is a deployment concern (Docker), not
    # something a local user should need to think about. Defaults to the same loopback-only
    # address as everything else.
    ui_host = os.getenv("UI_HOST", HOST)
    api_command, ui_command = build_commands(
        sys.executable, args.api_port, args.ui_port, headless=args.no_browser, ui_host=ui_host
    )
    guard = ProcessGuard()
    api = ui = None
    try:
        print(f"Démarrage de l'API sur http://{HOST}:{args.api_port} ...")
        api = guard.popen(api_command, cwd=root)
        if not wait_until_healthy(
            f"http://{HOST}:{args.api_port}/health", _API_START_TIMEOUT, lambda: api.poll() is None
        ):
            print("L'API n'a pas démarré (voir les messages ci-dessus).")
            return 1

        # The interface gets the API address, not the other secrets: it reads API_TOKEN itself
        # from .env / .env.ui and must not inherit the Gemini or encryption keys.
        ui_env = {key: value for key, value in os.environ.items() if key not in _REQUIRED[:2]}
        ui_env["API_URL"] = f"http://{HOST}:{args.api_port}"
        print(f"Démarrage de l'interface sur http://{ui_host}:{args.ui_port} ...")
        ui = guard.popen(ui_command, cwd=root, env=ui_env)
        print("InvoiceAI est prêt. Ctrl+C pour arrêter les deux serveurs.")

        while api.poll() is None and ui.poll() is None:
            time.sleep(1.0)
        print("Un des serveurs s'est arrêté : arrêt de l'autre.")
        return 1
    except KeyboardInterrupt:
        print("\nArrêt demandé.")
        return 0
    finally:
        _stop(ui)
        _stop(api)
