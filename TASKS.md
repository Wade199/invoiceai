# TASKS.md — Backlog & Suivi des tâches

> Mis à jour à chaque session de travail.
> Phases détaillées dans PROJECT_BRIEF.md §6.

---

## 🔥 En cours (P0 — Setup & Design)

| # | Tâche | Priorité | Statut | Estimation |
|---|-------|----------|--------|------------|
| 1 | Scaffold arborescence + config (pyproject, requirements, .env.example, .gitignore, Makefile, .streamlit) | High | ✅ Done | 1h |
| 2 | `scripts/generate_fake_invoices.py` (reportlab + faker) | High | ✅ Done | — |
| 3 | `git init` + commit initial + tag `v0.0` | High | ✅ Done | — |
| 4 | Générer les 5 factures fictives (`python scripts/generate_fake_invoices.py`) | Med | 📋 TODO | 5 min |
| 5 | Wireframes Excalidraw (4 écrans) → export PNG dans `docs/` | Med | 📋 TODO | 1-2h |

---

## 📋 À faire (Backlog priorisé)

| # | Tâche | Priorité | Dépendances | Estimation |
|---|-------|----------|-------------|------------|
| 6 | P1 — `src/ocr/extractor.py` (pdfplumber) | High | #4 | 1-2j |
| 7 | P1 — Validation upload (`src/api/security.py`) | High | — | 0.5j |
| 8 | P1 — Tests OCR + script CLI `scripts/test_ocr.py` | High | #6 | 1j |
| 9 | P2 — Schemas Pydantic v2 (`src/models/schemas.py`) | High | — | 0.5j |
| 10 | P2 — Adapter Gemini (`src/llm/gemini_adapter.py`) + prompt engineering documenté | High | #9 | 2-3j |
| 11 | P2 — Validation métier chiffres (`src/services/validate_invoice.py`) | High | #10 | 1j |
| 12 | P2 — Cache SHA-256 + rate limiting (`tenacity`) | Med | #10 | 1j |
| 13 | P3 — API REST FastAPI (upload/extract/history/export/delete) | High | #6, #10 | 2-3j |
| 14 | P3 — SQLAlchemy 2.x + SQLite | High | #13 | 1j |
| 15 | P4 — UI Streamlit (4 écrans) | High | #13 | 2-3j |
| 16 | P5 — README final + Docker + CI + repo GitHub public | Med | P1-P4 | 2-3j |

---

## ✅ Terminé

| # | Tâche | Date | Notes |
|---|-------|------|-------|
| 0 | Cahier des charges V1.0 (`PROJECT_BRIEF.md`) | 2026-09-18 | Cadrage validé avec Ibrahima |
| 1-3 | Scaffold P0 (structure, config, git) | 2026-09-18 | Voir ci-dessus |

---

## 🚫 Bloqué

| # | Tâche | Bloquant | Action requise |
|---|-------|----------|----------------|
| — | — | — | — |

---

## 💡 Idées / Future (V2)

- [ ] Provider-agnostic (Claude/GPT interchangeables avec Gemini)
- [ ] Migration PostgreSQL
- [ ] Article technique Medium/Dev.to
- [ ] Vidéo démo montée 60-90s
- [ ] Coverage Codecov
- [ ] Support multi-devises / intégration compta

---

## 📊 Légende

| Statut | Signification |
|--------|--------------|
| 📋 TODO | Pas encore commencé |
| 🔄 In Progress | En cours de développement |
| 🧪 Testing | En cours de test |
| 👁️ Review | En attente de review |
| ✅ Done | Terminé et validé |
| 🚫 Blocked | Bloqué, action requise |
| ❌ Cancelled | Annulé |
