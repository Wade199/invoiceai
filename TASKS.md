# TASKS.md — Backlog & Suivi des tâches

> Mis à jour à chaque session de travail.
> Phases détaillées dans PROJECT_BRIEF.md §6.

---

## 🔥 En cours

**P4 terminé** (UI + passe navigateur + captures + thème clair/sombre). Prochaine étape : finir P5 (tâche 16 — Docker + CI + repo public) ou retenter la tâche 19 (quota/503 Gemini) plus tard dans la journée.

---

## 📋 À faire (Backlog priorisé)

| # | Tâche | Priorité | Dépendances | Estimation |
|---|-------|----------|-------------|------------|
| 16 | P5 — reste : Docker + CI + décider de rendre le repo GitHub public (README déjà fini, captures incluses) | Med | P1-P4 | 2-3j |
| 19 | Rejouer `pytest -m slow` avec Gemini réel — **tenté le 2026-09-22 : 1 échec (503 « high demand », panne temporaire Google, géré correctement par le retry/`ProviderTimeoutError`) + 1 ignoré (quota épuisé après les retries)**. Pas un bug — à retenter plus tard dans la journée | Med | — | 0.25j |
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
| 14 | P3 — Base SQLite + SQLAlchemy : table `invoices` (payload chiffré), dépôt `InvoiceRepository`, rétention 30 j, suppression cache + base | 2026-09-21 | 268 tests ; revue : `docs/security/P3_DATABASE_REVIEW.md` |
| 13c | P3 — Export CSV (`src/services/export.py`) : factures + lignes, format Excel FR (`;`, virgule, BOM), neutralisation des formules | 2026-09-21 | 314 tests ; revue : `docs/security/P3_EXPORT_REVIEW.md` |
| 13b | P3 — API REST FastAPI : `POST/GET/PUT/DELETE /invoices`, export CSV, `/health`, jeton, contrôle de l'hôte, en-têtes, limiteurs, purge au démarrage | 2026-09-21 | 387 tests ; revue : `docs/security/P3_API_REVIEW.md` |
| — | Revue sécurité P2 v2, tag `v0.2.1` | 2026-09-20 | `docs/security/P2_SECURITY_REVIEW.md` ; test injection sur API réelle validé le 2026-09-21 |
| 21 | Passe dans un vrai navigateur (P4) + captures d'écran pour le README | 2026-09-22 | Upload/Résultat/Historique/Export vérifiés ; facture hostile confirmée en texte littéral ; thème clair/sombre natif ajouté et vérifié |
| 20 | Excel : formules neutralisées, confirmé pendant la passe navigateur (2026-09-21). `Host`/CORS testés en direct (2026-09-22) : `Host` usurpé → 400 (`TrustedHostMiddleware`, avant même la vérification du jeton) ; aucune route CORS déclarée → un navigateur bloquerait tout appel cross-origin authentifié (le preflight `OPTIONS` renvoie 405) | 2026-09-22 | — |

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
