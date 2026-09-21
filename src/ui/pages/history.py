from __future__ import annotations

import streamlit as st

from src.ui import services
from src.ui.errors import UiError
from src.ui.history_logic import (
    CURRENT_RECORD_KEY,
    MAX_ROWS,
    STATUS_CHOICES,
    delete_many,
    ids_for_selection,
    limit_reached,
    to_frame,
)
from src.ui.safe import safe

TABLE_KEY = "history_table"
PENDING_DELETE_KEY = "history_pending_delete"  # ids waiting for the user's confirmation
EXPORT_IDS_KEY = "export_ids"  # handed over to the Export page
FLASH_KEY = "history_flash"

st.title("📚 Historique des extractions")

if flash := st.session_state.pop(FLASH_KEY, None):
    st.success(flash)

# --- filters ---
search_column, from_column, to_column, status_column = st.columns([3, 2, 2, 2])
query = search_column.text_input(
    "Recherche", max_chars=100, placeholder="Fournisseur, client, n° de facture, fichier…"
)
date_from = from_column.date_input("Du", value=None, format="YYYY-MM-DD")
date_to = to_column.date_input("Au", value=None, format="YYYY-MM-DD")
status_label_choice = status_column.selectbox("Fiabilité", list(STATUS_CHOICES))

# --- the list ---
try:
    rows = services.get_client().list_invoices(
        query=query.strip() or None,
        date_from=date_from,
        date_to=date_to,
        status=STATUS_CHOICES[status_label_choice],
        limit=MAX_ROWS,
    )
except UiError as error:
    st.error(safe(error), icon="❌")
    st.stop()

filtered = bool(query.strip() or date_from or date_to or STATUS_CHOICES[status_label_choice])
if not rows:
    st.info(
        "Aucune facture ne correspond à ces filtres."
        if filtered
        else "Aucune facture pour l'instant. Envoyez un PDF depuis l'écran Upload."
    )
    st.stop()

st.caption(
    f"{len(rows)} facture{'s' if len(rows) > 1 else ''} trouvée{'s' if len(rows) > 1 else ''}"
)
if limit_reached(len(rows)):
    st.warning(f"Résultats limités aux {MAX_ROWS} plus récents : affinez la recherche.")

event = st.dataframe(
    to_frame(rows),
    on_select="rerun",
    selection_mode="multi-row",
    hide_index=True,
    width="stretch",
    key=TABLE_KEY,
)
selected = ids_for_selection(rows, list(event.selection.rows))

# --- actions on the selection ---
open_column, export_column, delete_column = st.columns(3)
if open_column.button(
    "👁 Ouvrir", disabled=len(selected) != 1, help="Sélectionnez une seule facture"
):
    st.session_state[CURRENT_RECORD_KEY] = selected[0]
    st.switch_page("pages/result.py")
if export_column.button("⬇ Exporter la sélection", disabled=not selected):
    st.session_state[EXPORT_IDS_KEY] = selected
    st.switch_page("pages/export.py")
if delete_column.button("🗑 Supprimer la sélection", disabled=not selected):
    st.session_state[PENDING_DELETE_KEY] = selected  # asks for confirmation below

# Two-step confirmation on the page (a dialog would only re-run its own fragment).
pending: list[str] = st.session_state.get(PENDING_DELETE_KEY, [])
if pending:
    with st.container(border=True):
        plural = "s" if len(pending) > 1 else ""
        st.warning(
            f"Supprimer définitivement **{len(pending)}** facture{plural} ? "
            "Les factures, leurs copies chiffrées en cache et les données correspondantes dans "
            "la base sont effacées.",
            icon="⚠️",
        )
        confirm_column, cancel_column = st.columns(2)
        if confirm_column.button("Oui, supprimer", type="primary", key="confirm_bulk_delete"):
            report = delete_many(services.get_client(), pending, st.session_state)
            st.session_state.pop(PENDING_DELETE_KEY, None)
            st.session_state[FLASH_KEY] = report.summary
            st.rerun()
        if cancel_column.button("Annuler", key="cancel_bulk_delete"):
            st.session_state.pop(PENDING_DELETE_KEY, None)
            st.rerun()
