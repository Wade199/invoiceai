# TASKS.md — Backlog & Suivi des tâches

> Mis à jour à chaque session de travail.
> Phases détaillées dans PROJECT_BRIEF.md §6.

---

## 🔥 En cours

**V1.0 publiée + V1.1 (photo/scan) ajoutée.** Repo public, tag `v1.0` posé. **22** : code fait et poussé (commit `c726320`, CI verte), reste juste à vérifier le format multimodal contre la vraie API Gemini (quota épuisé aujourd'hui).

---

## 📋 À faire (Backlog priorisé)

| # | Tâche | Priorité | Dépendances | Estimation |
|---|-------|----------|-------------|------------|
| 22b | Relancer `tests/slow/test_gemini_real.py::test_provider_reads_a_photographed_invoice` une fois le quota Gemini rechargé — code inchangé, juste à re-tenter | Low | — | 0.05j (juste relancer) |
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
| 19 | `pytest -m slow` avec Gemini réel — schéma accepté, injection de prompt sans effet (fournisseur/montant inchangés, clé API absente de la sortie). Échec du 2026-09-22 confirmé transitoire (503 Google) | 2026-09-24 | 2/2 tests passent, ~80s |
| 17 | `tests/slow/test_pipeline_real.py` (5 factures + 1 test de cache) — **validé sur preuve partielle** : `fake_invoice_01.pdf` a réussi 2 fois de suite en conditions réelles (le code du pipeline fonctionne). Les 4 autres factures + le test de cache n'ont pas pu tourner : quota Gemini épuisé **sur les 3 modèles testés** (`gemini-flash-latest`, `gemini-3.6-flash`, `gemini-3.1-pro-preview`) — la leçon du 18/09 (« quota par modèle ») semble fausse ou incomplète, le plafond journalier paraît global au projet/compte. Code inchangé, se vérifiera seul dès que le quota se recharge (aucune action requise) | 2026-09-24 | Ruff clean, 678 tests rapides toujours verts |
| 16a | P5 — Docker (`Dockerfile`, `docker-compose.yml`, 1 seul conteneur car API+UI se parlent en `127.0.0.1`) + CI GitHub Actions (`ruff` + `pytest`, sans `-m slow`) + `docs/architecture.md` (2 diagrammes Mermaid). 2 vrais bugs trouvés et corrigés en testant (pas supposés) : `UI_HOST` ajouté dans `src/launcher.py` (un conteneur ne peut pas être atteint sur son propre `127.0.0.1` depuis l'extérieur — l'API reste verrouillée, seule l'UI est élargie) ; nettoyage d'erreur dans `src/api/upload.py` qui masquait l'erreur d'origine sous Linux (`NotADirectoryError` non filtrée par `missing_ok=True`), trouvé en testant dans un vrai conteneur Linux avant de pousser la CI. Ancien `docs/architecture_assistant_ia_factures.svg` (reliquat du brief V0 abandonné) supprimé, références corrigées | 2026-09-24 | CI vérifiée verte sur GitHub (`gh run watch`), pas juste en local ; conteneur Docker testé et ouvert dans un vrai navigateur |
| 22 | **V1.1 — Photo/scan de facture** (JPEG/PNG) via Gemini multimodal : `src/llm/gemini_adapter.extract_invoice_data_from_image()`, upload multi-type (`src/api/upload.py`), pipeline branché sur le MIME (`src/services/pipeline.py`), UI mise à jour (formats acceptés + avertissement de confidentialité spécifique). Compromis assumé avec Ibrahima : pas de masquage IBAN/e-mail/téléphone possible sur une image (contrairement au PDF) — averti dans l'UI avant tout envoi de photo. Décision documentée dans `TECHNICAL_DESIGN.md` §2.2b et `docs/security/P2_SECURITY_REVIEW.md` §6 | 2026-09-24 | Commit `c726320`, CI vérifiée verte sur GitHub. 699 tests (7 nouveaux/modifiés), `ruff`/`bandit`/`pip-audit` propres. **Format multimodal jamais confirmé contre la vraie API** (quota épuisé le jour même) — voir tâche #22b |
| 16b | Repo passé **public** (historique complet vérifié sans secret avant, `git log --all -S` sur tous les motifs de clés) + tag `v1.0` posé et poussé | 2026-09-24 | https://github.com/Wade199/invoiceai — V1.0 publiée |

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
