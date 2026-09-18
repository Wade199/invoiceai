# PROJECT_CONTEXT.md — Mémoire vivante du projet

> ⚠️ Source de vérité du projet (avec PROJECT_BRIEF.md). À mettre à jour après chaque décision importante.
> Dernière mise à jour : 2026-09-18

---

## 🎯 Vision

**Nom du projet** : InvoiceAI (dossier local `assistant-ia-devis-factures`)
**Objectif** : Extraire automatiquement les données de factures/devis PDF (fournisseur, dates, montants HT/TVA/TTC, lignes) et les exporter en CSV/Excel.
**Valeur principale** : Projet portfolio démontrant un pipeline IA complet (OCR → LLM structuré → validation métier → API → UI) à des recruteurs tech, PAS un SaaS commercial.

---

## 👥 Utilisateurs

| Profil | Besoins principaux | Priorité |
|--------|-------------------|----------|
| Recruteur tech (lecteur du repo) | Code lisible, testé, démonstrable en entretien | High |
| Ibrahima (dev) | Apprendre par la pratique (pair programming, pas de génération 100% IA) | High |
| PME (persona produit, hypothétique) | Gagner du temps sur la saisie manuelle de factures | Med |

---

## ✅ Fonctionnalités

### Planifiées (V1, voir PROJECT_BRIEF.md §6)
- [ ] P0 — Scaffold, wireframes, factures fictives de test
- [ ] P1 — Pipeline OCR (`pdfplumber`) + validation upload
- [ ] P2 — Extraction structurée LLM (Gemini) + validation métier + cache + rate limiting
- [ ] P3 — API REST (FastAPI + SQLite)
- [ ] P4 — UI Streamlit (4 écrans)
- [ ] P5 — Doc finale + Docker + CI

---

## 🏗️ Architecture

**Type** : Monolithe modulaire (API + UI dans le même repo, séparés en modules)
**Pattern** : Couches simples (api / services / llm / ocr / models / core), pas de DDD complexe (overkill pour un MVP portfolio)

```
[Utilisateur] → [Streamlit UI] → [FastAPI] → [services/validate_invoice]
                                          ↘ [ocr/extractor (pdfplumber)]
                                          ↘ [llm/gemini_adapter (LangChain + Gemini)]
                                          ↘ [SQLAlchemy → SQLite]
```

---

## 🛠️ Stack technique

| Couche | Technologie | Version | Raison du choix |
|--------|-------------|---------|-----------------|
| Langage | Python | 3.11+ | Cohérent avec l'objectif AI Software Engineer |
| Package manager | pip + requirements.txt | — | Lisible pour un recruteur, pas de courbe d'apprentissage (`uv` en V2) |
| LLM | Google Gemini (`gemini-flash-latest`) via `langchain-google-genai` | — | Free tier officiel sans CB, multimodal natif (PDF/images), architecture provider-agnostic prévue |
| OCR/PDF | `pdfplumber` | — | Couvre 90% des PDF textuels, pas de fallback en V1 |
| API | FastAPI + Pydantic v2 | — | Standard moderne Python, typage fort |
| Base de données | SQLite + SQLAlchemy 2.x | — | Suffisant pour un MVP portfolio (PostgreSQL en V2) |
| UI | Streamlit natif | — | Rapide à développer, pas de custom design en V1 |
| Tests | pytest | — | Standard Python |
| Lint/format | ruff | — | Rapide, tout-en-un (remplace flake8+black+isort) |
| Conteneur | ❌ aucun en V1 | — | Reporté en P5, alourdirait le démarrage |
| CI/CD | ❌ aucun en V1 | — | Reporté en P5 (GitHub Actions : ruff + pytest) |

---

## 📁 Structure du repository

```
assistant-ia-devis-factures/
├── src/
│   ├── ocr/          ← extraction texte PDF (pdfplumber)
│   ├── llm/           ← adapter Gemini + LangChain
│   ├── models/        ← schemas Pydantic v2
│   ├── services/       ← validation métier, cache SHA-256
│   ├── api/            ← endpoints FastAPI, sécurité upload
│   ├── core/           ← config (Pydantic Settings), logging
│   └── ui/             ← app Streamlit
├── tests/
├── scripts/
│   └── generate_fake_invoices.py
├── data/                ← factures fictives + SQLite (gitignored sauf .gitkeep)
├── docs/
│   ├── adr/
│   ├── security/
│   └── architecture_assistant_ia_factures.svg
├── .streamlit/config.toml
├── pyproject.toml
├── requirements.txt
├── .env.example
├── Makefile
├── PROJECT_BRIEF.md      ← cahier des charges V1.0 (source de vérité)
├── PROJECT_CONTEXT.md    ← ce fichier
├── TASKS.md
├── DECISIONS.md
└── README.md
```

---

## 🔑 Décisions importantes

Voir [`DECISIONS.md`](DECISIONS.md) pour le détail. Résumé :

| Date | Décision | Raison |
|------|----------|--------|
| 2026-09-18 | LLM = Google Gemini (pas Claude) | Free tier sans CB ; compte Anthropic Console sans crédits |
| 2026-09-18 | Stack V1 allégée (sans Docker/CI, pdfplumber seul, Streamlit natif) | Éviter l'overkill, focus apprentissage + démonstrabilité |
| 2026-09-18 | Méthode pair programming (P1-P4 codés par Ibrahima) | Zéro apprentissage si 100% généré par IA, contre-productif en entretien |

---

## ⚠️ Contraintes

- **Sécurité upload** : taille max 10 MB, MIME `application/pdf` uniquement
- **RGPD** : rétention configurable (30j par défaut), endpoint `DELETE /invoice/{id}`
- **Rate limiting** : Gemini free tier = 15 req/min → retry + cache SHA-256
- **Fiabilité LLM** : validation arithmétique obligatoire (les LLM hallucinent des chiffres)
- **Budget** : 0€ (free tier uniquement)
- **Délai** : pas de deadline stricte, projet mené en parallèle de 2 autres

---

## 📐 Conventions de code

- **Langue** : code + docstrings + docs internes en **anglais** ; UI en **français** (cible PME France)
- **Branches** : `main` + `feature/pX-nom` par phase
- **Commits** : Conventional Commits en anglais (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`)
- **PR** : une PR par phase (même en solo), merge après review perso
- **Tests** : au moins 1 test unitaire par fonction critique (OCR, LLM, validation) — pas de coverage imposé en V1

---

## 🔒 Sécurité

- Secrets gérés via `.env` (jamais commité, voir `.gitignore`) + `secrets/.env` central du workspace
- Authentification : aucune en V1 (app locale mono-utilisateur, pas de déploiement public prévu)
- Points sensibles : upload PDF (taille/MIME), clé `GOOGLE_API_KEY`, données personnelles dans les factures (RGPD)
- Checklist complète avant toute release publique : [`docs/security/SECURITY_CHECKLIST.md`](docs/security/SECURITY_CHECKLIST.md)

---

## 🧪 Tests

| Type | Framework | Couverture cible |
|------|-----------|-----------------|
| Unit | pytest | Fonctions critiques (OCR, validation, LLM parsing) — pas de % imposé en V1 |
| API | pytest + httpx TestClient | Endpoints principaux |
| Fixtures | `scripts/generate_fake_invoices.py` | 5 factures PDF fictives (reportlab + faker) |

---

## 🚀 Déploiement

- **Environnements** : local uniquement en V1 (pas de staging/prod)
- **Méthode** : `streamlit run` + `uvicorn` en local (Docker reporté en P5)
- **CI/CD** : aucun en V1 (GitHub Actions en P5)

---

## 📌 Prochaines étapes

1. [ ] Terminer P0 : wireframes Excalidraw (4 écrans) — action manuelle Ibrahima
2. [ ] Générer les 5 factures fictives via `python scripts/generate_fake_invoices.py`
3. [ ] Démarrer P1 (pipeline OCR) — Ibrahima code, Jarvis coache

---

## 🗒️ Notes & contexte additionnel

Le cahier des charges complet et non-négociable est dans [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md) —
toute décision de structure/stack doit s'y référer en priorité. Ce fichier
(`PROJECT_CONTEXT.md`) en est un résumé vivant, mis à jour au fil de l'avancement.
