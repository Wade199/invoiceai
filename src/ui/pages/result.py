from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from src.ui import services
from src.ui.errors import ApiError, UiError
from src.ui.format import day, days_left, status_label
from src.ui.models import InvoiceView
from src.ui.result_logic import (
    CURRENT_RECORD_KEY,
    FLASH_KEY,
    FormValues,
    LineValues,
    delete_invoice,
    form_from_view,
    validate_and_build,
)
from src.ui.safe import safe

_LINE_COLUMNS = ["description", "quantity", "unit_price", "total"]


@st.dialog("Supprimer cette facture ?")
def _confirm_delete(record_id: str) -> None:
    st.write(
        "Cette action est **définitive** : la facture, sa copie chiffrée en cache et les "
        "données correspondantes dans la base sont effacées."
    )
    confirm, cancel = st.columns(2)
    if confirm.button("Oui, supprimer", type="primary", key="confirm_delete"):
        problem = delete_invoice(services.get_client(), record_id, st.session_state)
        if problem:
            st.error(safe(problem), icon="❌")
            return
        st.rerun()
    if cancel.button("Annuler", key="cancel_delete"):
        st.rerun()


def _lines_from_editor(edited: pd.DataFrame) -> list[LineValues]:
    """Rows of the table, without the empty rows left by adding then abandoning a line."""

    def number(value) -> float:
        return math.nan if pd.isna(value) else float(value)

    lines = []
    for row in edited.to_dict("records"):
        cells = [row.get(name) for name in _LINE_COLUMNS]
        if all(pd.isna(cell) for cell in cells):
            continue
        description = "" if pd.isna(row.get("description")) else str(row["description"])
        lines.append(
            LineValues(
                description,
                number(row.get("quantity")),
                number(row.get("unit_price")),
                number(row.get("total")),
            )
        )
    return lines


def _left_column(view: InvoiceView) -> None:
    st.caption("Fichier")
    st.text(view.display_name)  # `st.text` shows the name literally
    st.caption("Traité le")
    st.text(day(view.created_at))
    remaining = days_left(view.expires_at)
    st.info(
        f"🕒 Suppression automatique le **{day(view.expires_at)}** "
        f"(dans {remaining} jour{'s' if remaining > 1 else ''}).",
    )
    st.markdown(f"**Fiabilité** : {status_label(view.status)}")
    if view.status == "high":
        st.success("Les montants sont cohérents.", icon="✅")
    for warning in view.invoice.warnings:
        st.warning(safe(warning), icon="⚠️")
    if view.status == "low" and not view.invoice.warnings:
        st.warning("L'extraction est à vérifier.", icon="⚠️")


def _form(view: InvoiceView) -> FormValues:
    """Draw the editable form and return what it holds (never trusted: validated on save)."""
    form = form_from_view(view)
    key = view.id  # a different record gets fresh widgets
    invoice_number = st.text_input("N° facture", form.invoice_number, max_chars=100, key=f"n_{key}")
    supplier = st.text_input("Fournisseur", form.supplier, max_chars=200, key=f"s_{key}")
    client = st.text_input("Client", form.client, max_chars=200, key=f"c_{key}")
    invoice_date = st.text_input(
        "Date de la facture", form.date, max_chars=100, help="Format AAAA-MM-JJ", key=f"d_{key}"
    )
    ht_column, tva_column, ttc_column = st.columns(3)
    subtotal = ht_column.number_input(
        "Montant HT (€)", value=form.subtotal_ht, step=0.01, format="%.2f", key=f"ht_{key}"
    )
    tva = tva_column.number_input(
        "Taux de TVA (%)", value=form.tva_percent, step=0.5, format="%.2f", key=f"tva_{key}"
    )
    total = ttc_column.number_input(
        "Montant TTC (€)", value=form.total_ttc, step=0.01, format="%.2f", key=f"ttc_{key}"
    )

    st.markdown("**Lignes de facturation**")
    table = pd.DataFrame(
        [
            {
                "description": line.description,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "total": line.total,
            }
            for line in form.lines
        ],
        columns=_LINE_COLUMNS,
    )
    edited = st.data_editor(
        table,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key=f"lines_{key}",
        column_config={
            "description": st.column_config.TextColumn("Désignation", max_chars=500),
            "quantity": st.column_config.NumberColumn("Qté", format="%g"),
            "unit_price": st.column_config.NumberColumn("PU HT (€)", format="%.2f"),
            "total": st.column_config.NumberColumn("Total HT (€)", format="%.2f"),
        },
    )
    return FormValues(
        invoice_number=invoice_number,
        date=invoice_date,
        supplier=supplier,
        client=client,
        subtotal_ht=subtotal,
        tva_percent=tva,
        total_ttc=total,
        lines=_lines_from_editor(edited),
    )


st.title("🧾 Résultat de l'extraction")

if flash := st.session_state.pop(FLASH_KEY, None):
    st.success(flash)

record_id = st.session_state.get(CURRENT_RECORD_KEY)
if not record_id:
    st.info("Aucune facture sélectionnée. Envoyez un PDF ou ouvrez une facture de l'historique.")
    if st.button("📤 Aller à l'upload"):
        st.switch_page("pages/upload.py")
    st.stop()

try:
    view = services.get_client().get(record_id)
except ApiError as error:
    if error.status == 404:
        st.session_state.pop(CURRENT_RECORD_KEY, None)
        st.warning("Cette facture n'existe plus (supprimée ou expirée).", icon="🗑️")
    else:
        st.error(safe(error), icon="❌")
    st.stop()
except UiError as error:
    st.error(safe(error), icon="❌")
    st.stop()

if st.button("← Retour à l'historique"):
    st.switch_page("pages/history.py")

left, right = st.columns([1, 2], gap="large")
with left:
    _left_column(view)
with right:
    with st.form(f"edit_{view.id}"):
        values = _form(view)
        saved = st.form_submit_button("💾 Sauvegarder", type="primary")

if saved:
    payload, problems = validate_and_build(values)
    if problems:
        for problem in problems:
            st.error(problem, icon="⚠️")
    else:
        try:
            services.get_client().update(view.id, payload)
        except UiError as error:
            st.error(safe(error), icon="❌")
        else:
            st.session_state[FLASH_KEY] = "Modifications enregistrées."
            st.rerun()

if st.button("🗑 Supprimer cette facture"):
    _confirm_delete(view.id)
