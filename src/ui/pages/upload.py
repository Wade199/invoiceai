from __future__ import annotations

import streamlit as st

from src.ui import services
from src.ui.format import euro, status_label
from src.ui.safe import safe, safe_or_dash
from src.ui.upload_logic import MAX_FILES, Candidate, Outcome, process_batch

RESULTS_KEY = "upload_results"
ROUND_KEY = "uploader_round"  # changing the uploader's key is how its selection is emptied
CURRENT_RECORD_KEY = "current_record_id"


def _show_outcome(outcome: Outcome) -> None:
    name = safe(outcome.name)  # a file name is untrusted text
    if outcome.kind == "ok" and outcome.record is not None:
        record, invoice = outcome.record, outcome.record.invoice
        st.success(
            f"**{name}** — {safe_or_dash(invoice.supplier)} · {euro(invoice.total_ttc)} · "
            f"{status_label(record.status)}",
            icon="✅",
        )
        for warning in invoice.warnings:
            st.caption(f"⚠️ {safe(warning)}")
        if st.button("Voir le résultat", key=f"view_{record.id}"):
            st.session_state[CURRENT_RECORD_KEY] = record.id
            st.switch_page("pages/result.py")
        return
    hint = f" Réessayez dans {outcome.retry_after} s." if outcome.retry_after else ""
    message = f"**{name}** — {safe(outcome.message)}{hint}"
    if outcome.kind == "error":
        st.error(message, icon="❌")
    elif outcome.kind == "skipped":
        st.warning(message, icon="⚠️")
    else:
        st.info(message, icon="⏸️")


st.title("📤 Uploader une facture ou un devis")
st.caption(
    f"Formats acceptés : PDF · Taille max : 10 Mo par fichier · {MAX_FILES} fichiers par lot"
)

with st.expander("🔐 Confidentialité et limites", expanded=True):
    st.markdown(
        "- Le PDF est **supprimé du serveur** dès que l'extraction est terminée. Seul le résultat "
        "est conservé, **chiffré**, puis effacé automatiquement.\n"
        "- Avant l'envoi à Google Gemini, les **IBAN, e-mails et numéros de téléphone sont "
        "masqués**. Les noms, adresses et montants, eux, sont envoyés.\n"
        "- Plan gratuit de Gemini : **20 extractions par jour et par modèle**. En dehors de "
        "l'Espace économique européen, de la Suisse et du Royaume-Uni, Google peut réutiliser "
        "le contenu du plan gratuit : n'envoyez alors que des factures fictives."
    )

st.session_state.setdefault(ROUND_KEY, 0)
files = st.file_uploader(
    "Glissez vos PDF ici",
    type=["pdf"],
    accept_multiple_files=True,
    key=f"uploader_{st.session_state[ROUND_KEY]}",
)

if files and len(files) > MAX_FILES:
    st.warning(f"{MAX_FILES} fichiers maximum par lot : les suivants ne seront pas traités.")

if st.button("🚀 Lancer l'extraction", type="primary", disabled=not files):
    candidates = [Candidate(uploaded.name, uploaded.getvalue()) for uploaded in files]
    bar = st.progress(0.0, text="Préparation…")

    def on_progress(done: int, total: int, name: str) -> None:
        bar.progress(done / total, text=f"Extraction {done + 1}/{total} : {safe(name)}")

    with st.spinner("Extraction en cours (quelques secondes par facture)…"):
        results = process_batch(services.get_client(), candidates, on_progress)
    bar.empty()
    st.session_state[RESULTS_KEY] = results
    st.session_state[ROUND_KEY] += 1  # a fresh, empty uploader for the next batch
    st.rerun()

results: list[Outcome] = st.session_state.get(RESULTS_KEY, [])
if results:
    st.subheader("Résultats")
    for outcome in results:
        _show_outcome(outcome)
    if st.button("Effacer les résultats"):
        st.session_state[RESULTS_KEY] = []
        st.rerun()
