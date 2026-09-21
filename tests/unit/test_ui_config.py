from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.ui.config import UiSettings, load_settings, validate_api_url
from src.ui.errors import UiConfigError

TOKEN = "u" * 43


@pytest.fixture(autouse=True)
def _clean_ui_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("API_URL", raising=False)


# --- the address the token is sent to --------------------------------------------------------
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("http://localhost:8000/", "http://localhost:8000"),
        ("http://[::1]:8000", "http://[::1]:8000"),
        ("HTTP://LOCALHOST:8000", "HTTP://LOCALHOST:8000"),
        ("https://api.example.com", "https://api.example.com"),
        ("https://api.example.com:8443/base/", "https://api.example.com:8443/base"),
    ],
)
def test_safe_addresses_are_accepted(url: str, expected: str) -> None:
    assert validate_api_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",  # plain http to a remote host: the token would travel in clear
        "http://192.168.1.10:8000",
        "http://localhost.evil.example",  # looks local, is not
        "http://127.0.0.1.evil.example",
        "http://127.0.0.1@evil.example",  # the real host is what follows the @
        "http://user:pass@127.0.0.1:8000",  # credentials in the URL
        "http://127.0.0.1:not-a-port",
        "127.0.0.1:8000",  # no scheme
        "//evil.example",
        "ftp://127.0.0.1",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "http://",
        "",
    ],
)
def test_unsafe_addresses_are_refused(url: str) -> None:
    with pytest.raises(UiConfigError):
        validate_api_url(url)


# --- reading the settings --------------------------------------------------------------------
def test_settings_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("API_TOKEN", TOKEN)
    settings = load_settings(tmp_path)
    assert settings.api_token == TOKEN and settings.api_url == "http://127.0.0.1:8000"


def test_dot_env_ui_wins_over_dot_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"API_TOKEN={'a' * 43}\nAPI_URL=http://localhost:9000\n")
    (tmp_path / ".env.ui").write_text(f"API_TOKEN={TOKEN}\n")
    settings = load_settings(tmp_path)
    assert settings.api_token == TOKEN and settings.api_url == "http://127.0.0.1:8000"


def test_the_real_environment_wins_over_the_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text(f"API_TOKEN={'a' * 43}\n")
    monkeypatch.setenv("API_TOKEN", TOKEN)
    assert load_settings(tmp_path).api_token == TOKEN


def test_only_the_two_settings_are_read_and_nothing_leaks_into_the_process(
    tmp_path: Path,
) -> None:
    """The .env also holds the encryption key and the Gemini key: the UI must not carry them."""
    (tmp_path / ".env").write_text(
        f"API_TOKEN={TOKEN}\nGOOGLE_API_KEY=AQ.secret-gemini\nCACHE_ENCRYPTION_KEY_TEST=secret-key\n"
    )
    settings = load_settings(tmp_path)
    assert "CACHE_ENCRYPTION_KEY_TEST" not in os.environ and "GOOGLE_API_KEY" not in os.environ
    assert "secret" not in repr(settings) and not hasattr(settings, "google_api_key")
    assert set(vars(settings)) == {"api_url", "api_token"}


@pytest.mark.parametrize("token", [None, "", "short", "x" * 31])
def test_missing_or_weak_token_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str | None
) -> None:
    if token is not None:
        monkeypatch.setenv("API_TOKEN", token)
    with pytest.raises(UiConfigError, match="API_TOKEN"):
        load_settings(tmp_path)


def test_unsafe_address_in_the_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"API_TOKEN={TOKEN}\nAPI_URL=http://evil.example\n")
    with pytest.raises(UiConfigError, match="clear text"):
        load_settings(tmp_path)


def test_the_token_never_appears_in_repr_or_error_messages(tmp_path: Path) -> None:
    settings = UiSettings(api_url="http://127.0.0.1:8000", api_token=TOKEN)
    assert TOKEN not in repr(settings) and TOKEN not in str(settings)
    (tmp_path / ".env").write_text(f"API_TOKEN={TOKEN}\nAPI_URL=http://evil.example\n")
    with pytest.raises(UiConfigError) as info:
        load_settings(tmp_path)
    assert TOKEN not in str(info.value)
