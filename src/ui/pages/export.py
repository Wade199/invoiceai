from __future__ import annotations

import streamlit as st

from src.ui import services
from src.ui.errors import UiError
from src.ui.export_logic import (
    COLUMN_CHOICES,
    DEFAULT_COLUMNS,
    KIND_CHOICES,
    LOCALE_CHOICES,
    READY_KEY,
    build_request,
    forget_prepared_file,
    prepare_export,
)
from src.ui.history_logic import MAX_ROWS, STATUS_CHOICES
from src.ui.safe import safe

EXPORT_IDS_KEY = "export_ids"  # set by the History page ("Exporter la sélection")

st.title("⬇ Exporter les données")
st.caption("Choisissez le contenu, le format et les factures à exporter.")

selection: list[str] = st.session_state.get(EXPORT_IDS_KEY, [])

# --- what to export ---
kind_label = st.radio("Contenu", list(KIND_CHOICES), horizontal=True)
kind = KIND_CHOICES[kind_label]
locale_label = st.radio("Format des nombres", list(LOCALE_CHOICES))
locale = LOCALE_CHOICES[locale_label]
st.caption(
    "Fichier CSV (UTF-8) lisible par Excel, LibreOffice et Google Sheets. "
    "L'export Excel (.xlsx) n'est pas disponible dans cette version."
)

scope_options = (
    [f"Sélection de l'historique ({len(selection)} facture{'s' if len(selection) > 1 else ''})"]
    if selection
    else []
) + ["Par période et fiabilité"]
scope_label = st.radio("Factures concernées", scope_options)
scope = "selection" if selection and scope_label == scope_options[0] else "filters"

date_from = date_to = None
status = None
if scope == "filters":
    from_column, to_column, status_column = st.columns(3)
    date_from = from_column.date_input("Du", value=None, format="YYYY-MM-DD", key="export_from")
    date_to = to_column.date_input("Au", value=None, format="YYYY-MM-DD", key="export_to")
    status = STATUS_CHOICES[
        status_column.selectbox("Fiabilité", list(STATUS_CHOICES), key="export_status")
    ]
else:
    if st.button("Ne plus utiliser cette sélection"):
        st.session_state.pop(EXPORT_IDS_KEY, None)
        st.session_state.pop(READY_KEY, None)
        st.rerun()

columns: list[str] = list(DEFAULT_COLUMNS)
if kind == "invoices":
    columns = st.multiselect(
        "Colonnes à inclure",
        options=list(COLUMN_CHOICES),
        default=list(DEFAULT_COLUMNS),
        format_func=COLUMN_CHOICES.get,
    )

request, problems = build_request(
    scope=scope,
    ids=selection,
    kind=kind,
    locale=locale,
    columns=columns,
    date_from=date_from,
    date_to=date_to,
    status=status,
)

# --- preview and download ---
if request is not None:
    try:
        if request.ids is not None:
            count = len(request.ids)
        else:
            count = len(
                services.get_client().list_invoices(
                    date_from=date_from, date_to=date_to, status=status, limit=MAX_ROWS
                )
            )
    except UiError as error:
        st.error(safe(error), icon="❌")
        st.stop()
    detail = (
        f" · {len(columns)} colonne{'s' if len(columns) > 1 else ''}" if kind == "invoices" else ""
    )
    st.metric("Aperçu", f"{count} facture{'s' if count > 1 else ''}{detail}")
    if count == MAX_ROWS and request.ids is None:
        st.warning(f"L'export est limité aux {MAX_ROWS} factures les plus récentes.")
    if request.ids is None and count == 0:
        st.info("Aucune facture ne correspond : le fichier ne contiendrait que les en-têtes.")

for problem in problems:
    st.error(problem, icon="⚠️")

if st.button("📄 Préparer le fichier", type="primary", disabled=request is None):
    try:
        st.session_state[READY_KEY] = (request, prepare_export(services.get_client(), request))
    except UiError as error:
        st.session_state.pop(READY_KEY, None)
        st.error(safe(error), icon="❌")

ready = st.session_state.get(READY_KEY)
if request is not None and ready and ready[0] == request:  # only if it matches what is on screen
    exported = ready[1]
    st.download_button(
        f"⬇ Télécharger {exported.filename}",
        data=exported.content,
        file_name=exported.filename,
        mime="text/csv",
        on_click=lambda: forget_prepared_file(st.session_state),  # the file is taken: forget it
    )
    st.warning(
        "Ce fichier contient des données personnelles et **sort du chiffrement et de la "
        "suppression automatique** de l'application : supprimez-le après usage et ne le "
        "partagez pas.",
        icon="🔓",
    )
elif ready and request is not None:
    st.caption("Les choix ont changé : préparez à nouveau le fichier.")
