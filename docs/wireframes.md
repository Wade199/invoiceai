# Wireframes — InvoiceAI (V1.0)

> **C'est quoi un wireframe ?**
> Une maquette basse fidélité qui décrit **la structure** d'un écran (quels composants, où, dans quel ordre) — pas le style visuel (couleurs, fonts, ombres).
> Objectif : se mettre d'accord sur le *quoi* avant de coder, pour ne pas refaire l'UI 3 fois.
> Ici, on décrit les 4 écrans Streamlit en ASCII + noms de composants Streamlit natifs. Pas besoin d'outil de design.

---

## Convention de lecture

- Chaque bloc `┌── ... ──┐` = un écran.
- `st.xxx(...)` = composant Streamlit à utiliser dans le code (`src/ui/`).
- `[Bouton]` = un bouton cliquable.
- `▼` = un menu déroulant / select.
- `📎` = zone drag & drop.
- Les 4 écrans sont accessibles via une **sidebar de navigation** (`st.sidebar` avec `st.radio` ou `st.page_link` si multipages).

---

## 🧭 Navigation globale (sidebar, présente sur les 4 écrans)

```
┌─────────────────────────┐
│ 🧾 InvoiceAI            │  ← st.sidebar
│─────────────────────────│
│ ● Upload                │  ← st.radio("Navigation", [...])
│ ○ Résultat              │     (ou st.page_link si mode multipages)
│ ○ Historique            │
│ ○ Export                │
│─────────────────────────│
│ ⚙ RGPD : suppr. auto    │  ← st.caption
│    après 30 jours       │
│                         │
│ Version 0.1 · Gemini    │  ← st.caption (footer sidebar)
└─────────────────────────┘
```

---

## 📤 Écran 1 — Upload

**But** : uploader 1 à N PDF de factures/devis, valider la taille/MIME, lancer l'extraction.

```
┌──────────────────────────────────────────────────────────────────┐
│  📤 Uploader une facture ou un devis                             │  ← st.title
│                                                                  │
│  Formats acceptés : PDF · Taille max : 10 Mo par fichier         │  ← st.caption
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  📎  Glisser-déposer vos PDF ici                           │  │  ← st.file_uploader
│  │      ou cliquez pour parcourir                             │  │     (accept_multiple_files=True,
│  │                                                            │  │      type=["pdf"])
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ─────────────  Fichiers sélectionnés (2)  ─────────────         │
│  ✓ facture-orange-2026-09.pdf     · 342 Ko                       │  ← st.container
│  ✓ devis-fournisseur-x.pdf        · 128 Ko                       │     + boucle affichage
│                                                                  │
│  [   🚀 Lancer l'extraction   ]                                  │  ← st.button (primary)
│                                                                  │
│  ⚠ Fichier ignoré : contrat.docx (type non supporté)             │  ← st.warning (conditionnel)
└──────────────────────────────────────────────────────────────────┘
```

**États à gérer** :
- **Vide** : uniquement la zone drop.
- **Fichiers en attente** : liste + bouton actif.
- **Fichier rejeté** (taille > 10 Mo, MIME ≠ PDF) : `st.error(...)` avec le nom du fichier.
- **En cours d'extraction** : `st.spinner("Extraction en cours...")` + `st.progress()` si multi-fichiers.
- **Extraction terminée** : redirect auto vers l'écran Résultat (ou `st.success(...)` + bouton "Voir le résultat").

---

## 🧾 Écran 2 — Résultat (extraction d'une facture)

**But** : afficher les données extraites, permettre corrections manuelles, valider ou re-lancer.

```
┌──────────────────────────────────────────────────────────────────┐
│  🧾 Résultat de l'extraction                     [← Retour]      │  ← st.title + st.button
│                                                                  │
│  Fichier : facture-orange-2026-09.pdf                            │  ← st.caption
│  Extrait le : 2026-09-18 14:32  ·  Modèle : gemini-flash-latest  │
│                                                                  │
│  ┌─── 📄 Aperçu PDF ───┐  ┌─── ✏ Données extraites ──────────┐   │
│  │                     │  │                                  │   │
│  │  [Aperçu 1re page]  │  │  Fournisseur                     │   │  ← st.columns([1, 1])
│  │                     │  │  ┌────────────────────────────┐  │   │
│  │  (image PNG rendue  │  │  │ Orange SA                  │  │   │  ← st.text_input
│  │   depuis le PDF via │  │  └────────────────────────────┘  │   │
│  │   pdf2image)        │  │                                  │   │
│  │                     │  │  N° facture         Date         │   │
│  │                     │  │  ┌──────────┐  ┌──────────────┐  │   │
│  │  [◀]  1 / 2  [▶]    │  │  │ F-2026-09│  │ 2026-09-05  ▼│  │   │  ← st.date_input
│  │                     │  │  └──────────┘  └──────────────┘  │   │
│  │                     │  │                                  │   │
│  │                     │  │  Montant HT     TVA      TTC     │   │
│  │                     │  │  ┌────────┐  ┌──────┐ ┌────────┐ │   │
│  │                     │  │  │ 120.00 │  │ 24.00│ │ 144.00 │ │   │  ← st.number_input
│  │                     │  │  └────────┘  └──────┘ └────────┘ │   │
│  │                     │  │                                  │   │
│  │                     │  │  ⚠ Vérification cohérence :      │   │
│  │                     │  │    HT + TVA = TTC ✓              │   │  ← validation métier
│  └─────────────────────┘  └──────────────────────────────────┘   │
│                                                                  │
│  ── Lignes de facturation ──                                     │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ Désignation        │ Qté │ PU HT │ TVA % │ Total HT      │    │  ← st.data_editor
│  │ Forfait mobile 5G  │  1  │ 40.00 │  20   │  40.00        │    │     (éditable en place)
│  │ Location box fibre │  1  │ 80.00 │  20   │  80.00        │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  [  💾 Sauvegarder  ]   [  🔄 Re-extraire  ]   [  🗑 Supprimer ] │  ← st.columns + st.button
└──────────────────────────────────────────────────────────────────┘
```

**Points UX importants** :
- **Champs éditables** : l'utilisateur peut corriger l'extraction LLM (hallucinations possibles).
- **Validation métier visible** : si `HT + TVA ≠ TTC`, afficher un `st.warning` (tolérance ±0.02 € pour l'arrondi).
- **Bouton "Re-extraire"** : relance Gemini avec un prompt renforcé si le résultat est mauvais.
- **Bouton "Supprimer"** : DELETE RGPD immédiat (confirmation via `st.dialog` ou `st.warning` + double-clic).

---

## 📚 Écran 3 — Historique

**But** : lister toutes les factures traitées, filtrer, sélectionner pour voir/exporter.

```
┌──────────────────────────────────────────────────────────────────┐
│  📚 Historique des extractions                                   │  ← st.title
│                                                                  │
│  ┌── Filtres ─────────────────────────────────────────────┐      │
│  │  Recherche : [ Fournisseur, n° facture...       🔍  ]  │      │  ← st.text_input
│  │  Période :  [ 2026-08-01 ▼ ] → [ 2026-09-18 ▼ ]        │      │  ← st.date_input x2
│  │  Statut :   [ Tous ▼ ]                                 │      │  ← st.selectbox
│  └────────────────────────────────────────────────────────┘      │
│                                                                  │
│  12 factures trouvées                                            │  ← st.caption
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ ☐ │ Date       │ Fournisseur │ N° facture │ TTC  │ ⋯    │    │  ← st.dataframe
│  │ ☐ │ 2026-09-18 │ Orange SA   │ F-2026-09  │144.00│ [👁] │    │     (avec on_select)
│  │ ☐ │ 2026-09-15 │ EDF         │ 20260915   │ 87.20│ [👁] │    │     ou st.data_editor
│  │ ☐ │ 2026-09-10 │ Fournisseur X│ D-042     │523.00│ [👁] │    │     avec col checkbox
│  │ ...                                                       │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  [ ✓ Sélectionner tout ]  [ ⬇ Exporter sélection (CSV) ]         │  ← st.button
│                            [ 🗑 Supprimer sélection ]            │
│                                                                  │
│  ⚠ Suppression RGPD irréversible                                 │  ← st.info (permanent)
└──────────────────────────────────────────────────────────────────┘
```

**Comportement** :
- **Ligne cliquée** → ouvre l'écran Résultat en lecture seule.
- **Pagination** : `st.dataframe` gère nativement (ou pagination manuelle si > 100 lignes).
- **Suppression sélective** : boucle sur les IDs cochés → appel `DELETE /invoice/{id}`.

---

## ⬇ Écran 4 — Export

**But** : télécharger les données extraites en CSV ou Excel, par période ou sélection.

```
┌──────────────────────────────────────────────────────────────────┐
│  ⬇ Exporter les données                                          │  ← st.title
│                                                                  │
│  Choisissez le format et la période à exporter.                  │  ← st.caption
│                                                                  │
│  ┌── Format ──────────────────────────────────────────────┐      │
│  │  ● CSV (compatible Excel, LibreOffice, Google Sheets)  │      │  ← st.radio
│  │  ○ Excel (.xlsx, avec mise en forme)                   │      │
│  └────────────────────────────────────────────────────────┘      │
│                                                                  │
│  ┌── Période ─────────────────────────────────────────────┐      │
│  │  Du :  [ 2026-08-01 ▼ ]                                │      │  ← st.date_input
│  │  Au :  [ 2026-09-18 ▼ ]                                │      │
│  └────────────────────────────────────────────────────────┘      │
│                                                                  │
│  ┌── Colonnes à inclure ──────────────────────────────────┐      │
│  │  ☑ Date                    ☑ N° facture                │      │  ← st.multiselect
│  │  ☑ Fournisseur             ☑ Montant HT                │      │     ou plusieurs
│  │  ☑ Montant TVA             ☑ Montant TTC               │      │     st.checkbox
│  │  ☐ Lignes de facturation (fichier séparé)              │      │
│  └────────────────────────────────────────────────────────┘      │
│                                                                  │
│  Aperçu : 12 factures · 6 colonnes                               │  ← st.metric ou st.caption
│                                                                  │
│  [       ⬇ Télécharger le fichier       ]                        │  ← st.download_button
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Comportement** :
- Le clic sur "Télécharger" génère le fichier en mémoire (`io.BytesIO`) → `st.download_button` livre au navigateur.
- Nom de fichier : `invoices_YYYY-MM-DD_to_YYYY-MM-DD.csv`.

---

## 🎨 Choix de style (rappel du PROJECT_BRIEF)

- **Thème** : dark natif Streamlit (`.streamlit/config.toml`).
- **Pas de custom CSS lourd**, pas de Lucide, pas de fonts custom.
- **Langue UI** : 100% français.
- **Emojis** : sobres et fonctionnels (📤 📚 ⬇ 🧾), pas décoratifs.

---

## 🧭 Ordre d'implémentation suggéré (P4)

1. **Squelette navigation** (`src/ui/app.py`) : sidebar + 4 pages vides.
2. **Écran Upload** (le plus simple, valide la sécu upload).
3. **Écran Résultat** (le plus complexe, valide le flow LLM + DB).
4. **Écran Historique** (dépend de la DB déjà remplie).
5. **Écran Export** (dernier, réutilise l'historique).

---

## 📝 À valider avant de démarrer P1

- [ ] Les 4 écrans sont bien ceux attendus ?
- [ ] L'aperçu PDF en écran Résultat est-il pertinent en V1 (nécessite `pdf2image` + poppler) ou on skip ?
- [ ] Le `st.data_editor` pour éditer les lignes est-il OK, ou on reste en lecture seule en V1 ?
- [ ] Le bouton "Re-extraire" est-il en V1 ou V2 ?

> Si tu valides tel quel : on peut supprimer cette section une fois P4 démarré.
