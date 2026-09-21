# TASKS.md — Backlog & Suivi des tâches

> Mis à jour à chaque session de travail.
> Phases détaillées dans PROJECT_BRIEF.md §6.

---

## 🔥 En cours

Prochaine étape : **P3 — API + persistance** (13b). La couche sécurité de l'upload (13a) est faite : `docs/security/P3_UPLOAD_SECURITY_REVIEW.md`.

| # | Tâche | Priorité | Statut | Estimation |
|---|-------|----------|--------|------------|
| 13b | P3 — API REST FastAPI (upload/extract/history/export/delete) : câbler middleware + jeton + limiteurs (`src/api/security.py`, `upload.py`), `purge_expired()` et `purge_stale_uploads()` au démarrage, DELETE authentifié qui appelle `delete_cached()`, cible `make api` (127.0.0.1) | High | 📋 TODO | 2-3j |
| 14 | P3 — SQLAlchemy 2.x + SQLite (rétention RGPD 30 j) | High | 📋 TODO | 1j |

---

## 📋 À faire (Backlog priorisé)

| # | Tâche | Priorité | Dépendances | Estimation |
|---|-------|----------|-------------|------------|
| 15 | P4 — UI Streamlit (4 écrans) ; `escape_markdown()` sur chaque champ venant du LLM ; barre de progression (7-33 s / facture) | High | #13b | 2-3j |
| 16 | P5 — README final + Docker + CI + repo GitHub public | Med | P1-P4 | 2-3j |
| 17 | Test `slow` de `process_invoice` sur l'API réelle (5 factures fictives) | Low | — | 0.5j |
| 18 | Script CLI `scripts/test_ocr.py` (ex-tâche #8, optionnel) | Low | — | 0.5j |

---

## ✅ Terminé

| # | Tâche | Date | Notes |
|---|-------|------|-------|
| 0 | Cahier des charges V1.0 (`PROJECT_BRIEF.md`) | 2026-09-18 | Cadrage validé avec Ibrahima |
| 1-3 | Scaffold P0 (structure, config, git), tag `v0.0` | 2026-09-18 | |
| 4 | 5 factures fictives générées (`data/fake_invoices/`, non versionnées) | 2026-09-18 | |
| 5 | Wireframes des 4 écrans en texte (`docs/wireframes.md`) | 2026-09-18 | Excalidraw abandonné (voir `DECISIONS.md`) |
| 6 | P1 — OCR `src/ocr/extractor.py` + tests, tag `v0.1` | 2026-09-18 | Limites anti-DoS et processus isolé ajoutés le 2026-09-20 |
| 9 | P2 — Schémas Pydantic (`src/models/schemas.py`), sortie LLM nettoyée et bornée | 2026-09-18 | |
| 10 | P2 — Adapter Gemini + prompt documenté (`docs/prompt_engineering.md`) | 2026-09-20 | Erreurs du SDK réel mappées, quota journalier géré |
| 11 | P2 — Validation métier des montants (`validate_invoice.py`) | 2026-09-20 | |
| 12 | P2 — Cache SHA-256 chiffré (Fernet, TTL 30 j) + `process_invoice` | 2026-09-20 | Le « rate limiting tenacity » est devenu : retry sur limite par minute, pas sur quota journalier (20 req/jour/modèle) |
| 13a | P3 — Sécurité upload : middleware de taille, `save_upload`, jeton Bearer, limiteurs, traduction d'erreurs | 2026-09-21 | 209 tests ; revue : `docs/security/P3_UPLOAD_SECURITY_REVIEW.md` |
| — | Revue sécurité P2 v2, tag `v0.2.1` | 2026-09-20 | `docs/security/P2_SECURITY_REVIEW.md` ; test injection sur API réelle validé le 2026-09-21 |

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
