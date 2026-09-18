# PROJECT_BRIEF.md — assistant-ia-devis-factures

> **Nom public** : "InvoiceAI"
> **Version** : 1.0 (2026-09-18)
> **Auteur** : Ibrahima
> **Statut** : Cadrage validé — scaffold P0 à venir

---

## 1. Contexte & objectif

Projet portfolio destiné aux recruteurs tech (IA/ML/Fullstack) en 2026, développé par Ibrahima (dev junior 1-3 ans en montée vers AI Software Engineer).

**Fonctionnel** : outil qui extrait automatiquement les données de factures/devis PDF (fournisseur, dates, montants HT/TVA/TTC, lignes) et les exporte en CSV/Excel.

**Non-objectif** : ce n'est PAS un SaaS commercial. C'est un projet portfolio. Focus qualité de code + démonstrabilité, pas features à outrance.

---

## 2. Méthode de collaboration : Pair programming

**Règle centrale** : Jarvis NE GÉNÈRE PAS le projet en bloc. Il coache Ibrahima phase par phase.

| Phase | Rôle Jarvis | Rôle Ibrahima |
|-------|-------------|---------------|
| P0 — Scaffold | Génère 90% (boilerplate sans valeur pédagogique) | Vérifie, personnalise `PROJECT_CONTEXT.md`, comprend chaque fichier |
| P1-P4 — Code métier | Explique concept + montre 1er exemple + review le code d'Ibrahima | Code lui-même avec l'aide de Jarvis (questions, blocages, corrections) |
| P5 — Doc/CI/Docker | Génère 80% (technique, moins didactique) | Adapte + rédige les parties personnelles (README perso, posts LinkedIn) |

**Interdit** :
- Jarvis génère du code qu'Ibrahima ne peut pas expliquer ligne par ligne
- Ibrahima copie-colle sans comprendre → poser des questions à Jarvis systématiquement

---

## 3. Décisions figées (ne pas rediscuter)

| # | Décision | Valeur |
|---|----------|--------|
| 1 | Nom dossier local | `assistant-ia-devis-factures` |
| 2 | Nom public (README, LinkedIn) | "InvoiceAI" |
| 3 | Variable env clé LLM | `GOOGLE_API_KEY` (standard Google, reconnu par LangChain) |
| 4 | LLM principal | Google Gemini (`gemini-flash-latest`) |
| 5 | Langue code + docs internes | Anglais (commentaires, docstrings, README) |
| 6 | Langue commits | Conventionnels anglais (`feat:`, `fix:`, `docs:`) |
| 7 | Langue UI utilisateur | Français (cible PME France) |

---

## 4. Stack V1 (allégée volontairement)

| Couche | V1 | V2 (plus tard) |
|--------|----|----|
| Langage | Python 3.11+ | — |
| Package manager | `pip` + `requirements.txt` (classique, lisible recruteur) | `uv` si envie d'expérimenter |
| LLM | Gemini via `langchain-google-genai` | Provider-agnostic (Claude/GPT interchangeables) |
| Extraction texte | `pdfplumber` seul (couvre 90% des PDF textuels) | + PyMuPDF fallback ; Gemini multimodal fallback si PDF scanné |
| API | FastAPI + Pydantic v2 | — |
| DB | SQLite | PostgreSQL |
| ORM | SQLAlchemy 2.x | — |
| UI | Streamlit natif (pas de custom Lucide) | Custom Lucide + fonts + Next.js éventuel |
| Tests | `pytest` (unitaires basiques) | + coverage badge Codecov |
| Lint | `ruff` (format + lint) | — |
| Conteneurisation | ❌ V1 sans Docker | Docker + Compose en P5 seulement |
| CI | ❌ V1 sans CI | GitHub Actions en P5 seulement |

---

## 5. Points critiques non-négociables

Ces sujets DOIVENT être adressés (souvent oubliés dans les prompts génériques) :

### 5.1 Sécurité upload
- Limite taille PDF (ex : 10 MB max)
- Validation type MIME (`application/pdf` uniquement)
- Sanitisation nom de fichier (pas de `../`, pas d'exécutables)
- Stockage hors du répertoire web-accessible

### 5.2 RGPD (factures = données perso + comptables)
- Chiffrement au repos (SQLite chiffré ou factures dans dossier chiffré)
- Politique de rétention configurable (`DEFAULT_RETENTION_DAYS=30`)
- Endpoint `DELETE /invoice/{id}` fonctionnel
- Mention RGPD dans README + UI

### 5.3 Rate limiting (Gemini free tier = 15 req/min)
- Retry avec backoff exponentiel (`tenacity`)
- Cache en mémoire (ou disque) : hash SHA-256 du PDF → JSON extrait
- Message UI utilisateur si quota atteint

### 5.4 Validation métier LLM (les LLM hallucinent des chiffres)
- Vérifier `sum(lignes.total) ≈ subtotal_ht` (tolérance ±0,02 €)
- Vérifier `subtotal_ht × (1 + tva_rate) ≈ total_ttc`
- Si incohérence → flag `"extraction_confidence": "low"` dans la réponse
- Afficher un warning dans l'UI

### 5.5 Prompt engineering (le cœur du projet)
- Prompt structuré avec : instructions claires + format JSON attendu + 1-2 exemples few-shot + garde-fous ("if unsure, return null")
- Utiliser `PydanticOutputParser` de LangChain pour forcer le format
- Tester le prompt sur 5-10 factures variées avant de figer

---

## 6. Plan des 5 phases (V1)

### P0 — Setup & Design (1-2 j) — Jarvis génère
- [ ] Scaffold arborescence complète
- [ ] `pyproject.toml` (ruff) + `requirements.txt`
- [ ] `.env.example` avec toutes les variables
- [ ] `.gitignore` Python + secrets
- [ ] `README.md` skeleton avec placeholders
- [ ] `.streamlit/config.toml` thème dark simple (natif)
- [ ] `Makefile` : `dev`, `test`, `lint`
- [ ] Wireframes Excalidraw (4 écrans) → export PNG dans `docs/`
- [ ] Génération de 5 factures fictives PDF via `scripts/generate_fake_invoices.py` (`reportlab` + `faker`)
- [ ] `git init` + commit initial + tag `v0.0`

### P1 — Pipeline OCR (3-5 j) — Ibrahima code, Jarvis coache
- [ ] `src/ocr/extractor.py` avec `pdfplumber` uniquement
- [ ] Validation upload (taille, MIME) → `src/api/security.py`
- [ ] Tests unitaires sur les 5 factures fictives (`tests/test_ocr.py`)
- [ ] Script CLI `scripts/test_ocr.py <pdf_path>`
- [ ] Branch `feature/p1-ocr` → PR → merge → tag `v0.1`

### P2 — Extraction structurée LLM (5-7 j) — Ibrahima code, Jarvis coache
- [ ] Schemas Pydantic v2 (`src/models/schemas.py`)
- [ ] Adapter Gemini + LangChain (`src/llm/gemini_adapter.py`)
- [ ] **Prompt engineering documenté** (`docs/prompt_engineering.md`)
- [ ] Validation métier (règles cohérence chiffres) → `src/services/validate_invoice.py`
- [ ] Cache SHA-256 → JSON (`src/services/cache.py`)
- [ ] Rate limiting + retry (`tenacity`)
- [ ] Tests avec factures fictives + mock Gemini
- [ ] Branch `feature/p2-llm` → PR → merge → tag `v0.2`

### P3 — API REST (3-5 j) — Ibrahima code, Jarvis coache
- [ ] FastAPI : `POST /upload`, `POST /extract/{id}`, `GET /history`, `GET /export/{id}/csv`, `DELETE /invoice/{id}` (RGPD)
- [ ] SQLAlchemy 2.x + SQLite
- [ ] Config Pydantic Settings (`src/core/config.py`)
- [ ] Logging structuré
- [ ] Tests API (httpx TestClient)
- [ ] Branch `feature/p3-api` → PR → merge → tag `v0.3`

### P4 — UI Streamlit (2-3 j) — Ibrahima code, Jarvis coache
- [ ] 4 écrans : Upload / Résultat / Historique / Export
- [ ] Affichage warning si `extraction_confidence: low`
- [ ] Bouton "Supprimer" (RGPD)
- [ ] Screenshots dans `docs/screenshots/`
- [ ] GIF démo (ScreenToGif, 60-90s) → `docs/demo.gif`
- [ ] Branch `feature/p4-ui` → PR → merge → tag `v0.4`

### P5 — Doc + Docker + CI (2-3 j) — Jarvis génère 80%
- [ ] `README.md` final avec GIF + diagramme Mermaid + badges CI
- [ ] `docs/architecture.md`
- [ ] `Dockerfile` simple + `docker-compose.yml`
- [ ] `.github/workflows/ci.yml` (ruff + pytest)
- [ ] Section RGPD + Sécurité dans le README
- [ ] Repo GitHub public créé + push
- [ ] Tag `v1.0` — projet publiable

---

## 7. Livrables portfolio

### V1 (fin des 5 phases)
- Repo GitHub public propre
- README avec GIF démo + diagramme Mermaid + badges
- Post LinkedIn **écrit par Ibrahima** (Jarvis relit, ne rédige pas)

### V2 (optionnel, plus tard)
- Article technique Medium/Dev.to (écrit par Ibrahima, Jarvis relit)
- Vidéo démo montée 60-90s
- Coverage Codecov + provider-agnostic Claude/GPT
- Migration PostgreSQL
- Support multi-devises / arabe / intégration compta

---

## 8. Contraintes qualité (adaptées junior, pas overkill)

- **Typage** : type hints partout où possible, pas de `mypy strict` en V1
- **Docstrings** : sur les fonctions publiques, Google style, courtes
- **Tests** : au moins 1 test unitaire par fonction critique (OCR, LLM, validation) — pas de coverage 70% imposé en V1
- **Git** : 1 branche par phase, commits atomiques conventionnels, PR même en solo
- **Sécurité** : les 4 points critiques du §5 sont non-négociables

---

## 9. Éléments retirés du prompt initial (justifications)

| Retiré | Pourquoi |
|--------|----------|
| Multi-fallback OCR (PyMuPDF + pytesseract dès V1) | Overkill V1, pdfplumber suffit à 90% |
| `uv` comme package manager | Nouveau, courbe apprentissage, `pip` plus lisible recruteur |
| Docker multi-stage + CI dès P0 | Alourdit le démarrage, à faire en P5 |
| SQLAlchemy 2.x + Pydantic v2 en syntaxe avancée | On garde mais on reste simple |
| Streamlit custom Lucide + fonts + config avancée | Streamlit natif suffit pour un MVP |
| Coverage 70%+ obligatoire | Trop ambitieux V1, tests basiques d'abord |
| Article Medium + vidéo montée dans V1 | Reporté en V2 |
| Posts LinkedIn générés par IA | Détectés en 2026, mauvais pour branding perso |
| Approche "génère-moi tout le projet" | Zéro apprentissage, contre-productif en entretien |
| Questions bonus (multi-devises, arabe, QuickBooks) | Hors scope V1, à voir en V2 |

---

## 10. Prochaine action

Scaffold P0 à lancer dans une prochaine session (VS Code recommandé pour Ibrahima) via :

> `initialise un nouveau projet nommé assistant-ia-devis-factures`

Le brief actuel sert de référence pour le scaffold — Jarvis doit s'y référer pour toute décision de structure/stack/qualité.
