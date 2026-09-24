from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from src import launcher

GOOD = {
    "GOOGLE_API_KEY": "AQ.fake-gemini-key-for-tests",
    "CACHE_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "API_TOKEN": "t" * 43,
}


def _problems(tmp_path: Path, environ: dict[str, str], dotenv: str | None = None) -> list[str]:
    if dotenv is not None:
        (tmp_path / ".env").write_text(dotenv)
    return launcher.check_environment(tmp_path, environ)


def test_a_complete_configuration_has_no_problem(tmp_path: Path) -> None:
    assert _problems(tmp_path, GOOD) == []


def test_the_configuration_can_come_from_the_dot_env_file(tmp_path: Path) -> None:
    content = "".join(f"{key}={value}\n" for key, value in GOOD.items())
    assert _problems(tmp_path, {}, content) == []


def test_missing_settings_are_named_one_by_one(tmp_path: Path) -> None:
    problems = _problems(tmp_path, {})
    assert len(problems) == 3
    for key in GOOD:
        assert any(problem.startswith(key) for problem in problems)


def test_a_weak_token_and_an_invalid_key_are_reported(tmp_path: Path) -> None:
    problems = _problems(tmp_path, {**GOOD, "API_TOKEN": "short", "CACHE_ENCRYPTION_KEY": "nope"})
    assert any("API_TOKEN" in p and "trop courte" in p for p in problems)
    assert any("CACHE_ENCRYPTION_KEY" in p and "valide" in p for p in problems)


def test_no_secret_value_is_ever_printed(tmp_path: Path) -> None:
    secret = "SUPER-SECRET-VALUE-" + "x" * 30
    problems = _problems(
        tmp_path,
        {"GOOGLE_API_KEY": secret, "CACHE_ENCRYPTION_KEY": secret, "API_TOKEN": secret[:20]},
    )
    assert problems and all("SECRET" not in problem for problem in problems)


def test_the_real_environment_wins_over_the_file(tmp_path: Path) -> None:
    content = "GOOGLE_API_KEY=x\nCACHE_ENCRYPTION_KEY=broken\nAPI_TOKEN=short\n"
    assert _problems(tmp_path, GOOD, content) == []


def test_port_is_free_detects_a_listening_port() -> None:
    with socket.socket() as server:
        server.bind((launcher.HOST, 0))
        server.listen()
        port = server.getsockname()[1]
        assert launcher.port_is_free(port) is False
    assert launcher.port_is_free(port) is True


def test_commands_listen_on_localhost_only_and_hide_what_should_be_hidden() -> None:
    api, ui = launcher.build_commands("python", 8123, 8623, headless=True)
    assert api[:3] == ["python", "-m", "uvicorn"] and "--factory" in api
    assert "src.api.app:create_app" in api
    assert api[api.index("--host") + 1] == "127.0.0.1" and api[api.index("--port") + 1] == "8123"
    assert "--no-access-log" in api and "--no-server-header" in api  # searches are in the URL
    assert ui[:4] == ["python", "-m", "streamlit", "run"] and "src/ui/app.py" in ui
    assert ui[ui.index("--server.address") + 1] == "127.0.0.1"
    assert ui[ui.index("--server.headless") + 1] == "true"
    assert "0.0.0.0" not in " ".join(api + ui)
    assert launcher.build_commands("p", 1, 2, headless=False)[1][-1] == "false"


def test_ui_host_widens_only_the_interface_never_the_api() -> None:
    """A container's 127.0.0.1 isn't reachable from outside it: only the UI may be widened."""
    api, ui = launcher.build_commands("python", 8123, 8623, headless=True, ui_host="0.0.0.0")
    assert api[api.index("--host") + 1] == "127.0.0.1"  # the API is never widened
    assert ui[ui.index("--server.address") + 1] == "0.0.0.0"


def test_wait_until_healthy_gives_up_when_the_process_is_gone() -> None:
    assert launcher.wait_until_healthy("http://127.0.0.1:1/health", 5.0, lambda: False) is False


def test_main_refuses_to_start_with_a_bad_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for key in GOOD:
        monkeypatch.delenv(key, raising=False)
    assert launcher.main(["--no-browser"], root=tmp_path) == 2
    output = capsys.readouterr().out
    assert "Impossible de démarrer" in output and "API_TOKEN est absente" in output


def test_main_refuses_a_port_that_is_already_in_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for key, value in GOOD.items():
        monkeypatch.setenv(key, value)
    with socket.socket() as busy:
        busy.bind((launcher.HOST, 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert launcher.main(["--api-port", str(port)], root=tmp_path) == 2
    assert f"port {port}" in capsys.readouterr().out


def test_this_interpreter_is_the_one_used_to_start_the_servers() -> None:
    api, ui = launcher.build_commands(sys.executable, 1, 2, headless=True)
    assert api[0] == ui[0] == sys.executable


# --- the main loop, with fake processes (the real one is in tests/integration) ------------------
class _FakeProcess:
    def __init__(self, exits_after_polls: int | None = None) -> None:
        self.exits_after = exits_after_polls
        self.polls = 0
        self.exit_code: int | None = None
        self.terminated = False

    def poll(self):
        if self.exit_code is not None:
            return self.exit_code
        if self.exits_after is not None and self.polls >= self.exits_after:
            self.exit_code = 1
            return 1
        self.polls += 1
        return None

    def terminate(self) -> None:
        self.terminated = True
        self.exit_code = 0

    def wait(self, timeout=None) -> int:
        return 0

    def kill(self) -> None:
        self.exit_code = -9


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind((launcher.HOST, 0))
        return probe.getsockname()[1]


@pytest.fixture
def fake_servers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Complete configuration, fake child processes, no real waiting."""
    for key, value in GOOD.items():
        monkeypatch.setenv(key, value)
    started: list[tuple[list[str], dict, _FakeProcess]] = []
    plan = {"api": _FakeProcess(), "ui": _FakeProcess(exits_after_polls=2)}

    def popen(self, command, **kwargs):
        process = plan["api"] if "uvicorn" in command else plan["ui"]
        started.append((command, kwargs, process))
        return process

    monkeypatch.setattr(launcher.ProcessGuard, "popen", popen)
    monkeypatch.setattr(launcher, "wait_until_healthy", lambda *args, **kwargs: True)
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
    return started, plan


def test_the_interface_process_does_not_inherit_the_secret_keys(fake_servers, tmp_path) -> None:
    started, _plan = fake_servers
    api_port = _free_port()
    launcher.main(
        ["--no-browser", "--api-port", str(api_port), "--ui-port", str(_free_port())], tmp_path
    )

    (_api_cmd, api_kwargs, _), (_ui_cmd, ui_kwargs, _) = started
    ui_env = ui_kwargs["env"]
    assert "GOOGLE_API_KEY" not in ui_env and "CACHE_ENCRYPTION_KEY" not in ui_env
    assert ui_env["API_URL"] == f"http://127.0.0.1:{api_port}"
    assert ui_env["API_TOKEN"] == GOOD["API_TOKEN"]  # the one secret the interface needs
    assert "env" not in api_kwargs  # the API inherits everything: it is the one holding the keys


def test_ui_host_env_var_reaches_the_interface_command(
    fake_servers, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Docker use case: UI_HOST=0.0.0.0 widens the interface, never the API."""
    monkeypatch.setenv("UI_HOST", "0.0.0.0")
    started, _plan = fake_servers
    launcher.main(
        ["--no-browser", "--api-port", str(_free_port()), "--ui-port", str(_free_port())], tmp_path
    )
    (api_cmd, _, _), (ui_cmd, _, _) = started
    assert api_cmd[api_cmd.index("--host") + 1] == "127.0.0.1"
    assert ui_cmd[ui_cmd.index("--server.address") + 1] == "0.0.0.0"


def test_the_api_is_started_first_and_both_are_stopped_when_one_dies(
    fake_servers, tmp_path
) -> None:
    started, plan = fake_servers
    result = launcher.main(
        ["--no-browser", "--api-port", str(_free_port()), "--ui-port", str(_free_port())], tmp_path
    )
    assert result == 1  # the interface died: not a clean exit
    assert "uvicorn" in started[0][0] and "streamlit" in started[1][0]
    assert plan["api"].terminated  # the survivor was stopped
    assert plan["ui"].exit_code is not None  # the one that died is not left running either


def test_ctrl_c_stops_both_servers_and_exits_cleanly(
    fake_servers, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _started, plan = fake_servers
    plan["ui"] = _FakeProcess()  # never exits by itself

    def interrupt(_seconds) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(launcher.time, "sleep", interrupt)
    result = launcher.main(
        ["--no-browser", "--api-port", str(_free_port()), "--ui-port", str(_free_port())], tmp_path
    )
    assert result == 0 and plan["api"].terminated and plan["ui"].terminated


def test_an_api_that_never_becomes_healthy_is_stopped_and_the_interface_never_started(
    fake_servers, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, plan = fake_servers
    monkeypatch.setattr(launcher, "wait_until_healthy", lambda *args, **kwargs: False)
    result = launcher.main(
        ["--no-browser", "--api-port", str(_free_port()), "--ui-port", str(_free_port())], tmp_path
    )
    assert result == 1 and len(started) == 1 and plan["api"].terminated


def test_the_browser_is_only_opened_when_asked(fake_servers, tmp_path) -> None:
    started, _plan = fake_servers
    launcher.main(["--api-port", str(_free_port()), "--ui-port", str(_free_port())], tmp_path)
    ui_command = started[1][0]
    assert ui_command[ui_command.index("--server.headless") + 1] == "false"
