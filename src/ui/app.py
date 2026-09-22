from __future__ import annotations

import sys
from pathlib import Path

# `streamlit run src/ui/app.py` puts src/ui on sys.path, not the project root.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402

from src.ui import services  # noqa: E402
from src.ui.errors import UiError  # noqa: E402
from src.ui.safe import safe  # noqa: E402

_VERSION = "0.3"
_ASSETS = Path(__file__).resolve().parent / "assets"


def main() -> None:
    st.set_page_config(page_title="InvoiceAI", page_icon=str(_ASSETS / "icon.png"), layout="wide")
    st.logo(str(_ASSETS / "logo.png"), size="large", icon_image=str(_ASSETS / "icon.png"))
    navigation = st.navigation(
        [
            st.Page("pages/upload.py", title="Upload", icon="📤", default=True),
            st.Page("pages/result.py", title="Résultat", icon="🧾"),
            st.Page("pages/history.py", title="Historique", icon="📚"),
            st.Page("pages/export.py", title="Export", icon="⬇️"),
        ]
    )
    with st.sidebar:
        st.caption("🔒 Données chiffrées · suppression automatique")
        st.caption(f"Version {_VERSION} · Gemini")

    try:
        services.get_client().check()
    except UiError as error:
        st.error(safe(error), icon="🔌")
        st.button("Réessayer")  # any click reruns the script
        st.stop()

    navigation.run()


main()
