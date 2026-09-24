# SECURITY_CHECKLIST.md — Checklist avant release

> À passer avant chaque mise en production.
> Projet : InvoiceAI | Version : v1.0 | Date : 2026-09-24
>
> Légende : `[x]` vérifié · `[ ]` non applicable (voir note) · les items génériques du
> template qui ne concernent pas un outil local mono-utilisateur sont marqués **N/A** avec la
> raison, plutôt que cochés sans vérification.

---

## 🏗️ Architecture & Réseau

- [x] Aucune BDD exposée directement sur Internet — SQLite locale, jamais accessible réseau
- [ ] **N/A** Segmentation réseau frontend/backend/db — un seul process local, pas de réseau à segmenter
- [ ] **N/A** TLS sur les endpoints publics — pas d'endpoint public, HTTP sur `127.0.0.1` uniquement (documenté : "ne jamais exposer tel quel")
- [x] Ports inutiles fermés — seuls 8000 (API, interne même en Docker) et 8501 (UI) existent, aucun autre service
- [ ] **N/A** Interface d'administration — n'existe pas dans ce projet
- [x] Rate limiting actif — sur `POST /invoices` (fenêtre glissante + limite de concurrence) ; pas sur les autres routes (risque résiduel documenté, faible : un seul utilisateur détient le jeton)
- [ ] **N/A** WAF — pas d'exposition Internet

## 🔐 Authentification & Autorisation

- [ ] **N/A** MFA — pas de comptes, un seul jeton partagé (modèle mono-utilisateur assumé)
- [ ] **N/A** Mots de passe — aucun mot de passe dans ce projet
- [ ] **N/A** Expiration des tokens — le jeton est statique (`.env`), pas de rotation automatique en V1
- [ ] **N/A** Sessions — API sans état (bearer token à chaque requête, pas de session serveur)
- [x] Principe du moindre privilège — API ne détient que ses propres secrets ; l'UI ne reçoit ni `GOOGLE_API_KEY` ni `CACHE_ENCRYPTION_KEY` (vérifié par test)
- [x] Comparaison du jeton en temps constant (résiste au timing attack)

## 🔑 Secrets

- [x] Aucun secret dans le code source — vérifié par lecture + `bandit`
- [x] Aucun secret dans l'historique Git — `git log --all -S` sur tous les motifs de clés (Google, Anthropic, GitHub, génériques), **exécuté le 2026-09-24 avant de passer le repo public**, rien trouvé
- [x] `.env` jamais suivi par Git — vérifié (`git check-ignore`, aucun historique)
- [x] Secret scanning activé côté GitHub — `secret_scanning` + `secret_scanning_push_protection` actifs (auto-activés au passage en public)
- [ ] Rotation des credentials documentée — pas de procédure écrite ; à faire si une clé est un jour compromise (voir `INCIDENT_RESPONSE.md`)

## 🌐 Application Web / API (OWASP)

- [x] Inputs validés côté serveur — Pydantic, UUID canoniques, allowlist de colonnes export
- [x] ORM avec requêtes paramétrées (SQLAlchemy), aucune concaténation SQL — vérifié par lecture + testé en direct (payloads `' OR '1'='1`, etc. → 422 avant la base)
- [x] Outputs encodés (XSS) — `safe()`/`escape_markdown` sur tout texte venant du LLM ; vérifié par tests + en navigateur réel (facture hostile affichée en texte littéral)
- [ ] **N/A** CSRF — API à jeton Bearer explicite, pas de cookies/session ambiante qu'un navigateur attacherait automatiquement ; CSRF classique ne s'applique pas à ce modèle
- [x] Headers de sécurité — `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Content-Security-Policy: default-src 'none'`, `Cache-Control: no-store` sur **toutes** les réponses (200/401/404/413/422/500), vérifié en direct
- [x] Messages d'erreur sans détail sensible — 9 erreurs métier → messages fixes en français, jamais de chemin/trace ; vérifié par tests + en direct
- [x] Upload : type, taille et contenu vérifiés — MIME **et** octets `%PDF-`, taille bornée, testé en direct avec faux PDF/exécutable/fichier vide → tous rejetés
- [ ] **N/A** SSRF / URLs externes — l'app ne fait qu'un seul appel sortant fixe (Gemini), aucune URL fournie par l'utilisateur n'est jamais récupérée côté serveur
- [x] IDOR — testé en direct (UUID malformés, traversée de chemin sur l'ID) → 422/404 systématique ; modèle mono-utilisateur donc pas de "ressource d'un autre utilisateur" à protéger

## 📦 Dépendances

- [x] `pip-audit` exécuté sans vulnérabilité — relancé le 2026-09-24, 0 trouvée
- [x] Lockfile à jour et committé — `requirements.txt`
- [x] Image Docker basée sur une image officielle à jour — `python:3.11-slim`
- [ ] Scan CVE niveau OS de l'image (Trivy/Docker Scout) — non fait (nécessite une connexion Docker Hub), voir gap #5 de l'audit

## 🔄 CI/CD

- [x] Secret scanning — actif côté GitHub (repo public)
- [x] Dependency scanning — `pip-audit` en local ; **Dependabot pas encore activé côté GitHub** (gap #1 de l'audit, à corriger)
- [x] Tests automatiques passent à 100% — CI GitHub Actions, `lint` + `test`, vérifiés verts en vrai (`gh run watch`)
- [ ] Branches protégées — pas de protection de branche sur `master` (projet solo, pas de collaborateur ; acceptable en l'état, à activer si des contributeurs rejoignent)
- [x] Artefacts de build reproductibles — `Dockerfile` déterministe, dépendances verrouillées

## 📊 Logs & Monitoring

- [x] Aucun mot de passe / token dans les logs — vérifié en direct (`grep` du jeton et de la clé Gemini dans les logs générés pendant toute une session de tests d'attaque : 0 occurrence)
- [x] Erreurs journalisées sans données sensibles — type d'exception + code HTTP seulement
- [ ] **N/A** Alertes automatiques (brute force, etc.) — pas de système de monitoring pour un outil local mono-utilisateur ; les tentatives d'auth échouées ne sont pas comptées/alertées (acceptable : un seul utilisateur légitime, pas de surface d'attaque distante)
- [ ] **N/A** Logs centralisés — process local, logs dans le terminal/fichier local uniquement

## 💾 Données & Backup

- [x] Données sensibles chiffrées au repos — Fernet (AES + HMAC) sur la base ET le cache, vérifié en lisant les octets bruts du fichier `.db`
- [ ] **N/A** Chiffrement en transit — pas de réseau à traverser (`127.0.0.1`)
- [ ] Sauvegardes automatisées — aucune (données locales, régénérables en re-uploadant les PDF) ; `CACHE_ENCRYPTION_KEY` doit être sauvegardée manuellement (demandé à Ibrahima, fait)
- [x] Rétention définie et appliquée — 30 jours (`DEFAULT_RETENTION_DAYS`), purge testée

## 🌍 Configuration des environnements

- [x] Stack traces désactivées — `showErrorDetails="none"` (Streamlit), messages fixes (API)
- [x] Configuration externalisée — tout via `.env`, rien en dur dans le code
- [ ] **N/A** Séparation dev/staging/prod — un seul environnement (usage local personnel)

---

## 📋 Security Gate — Synthèse finale

```
SECURITY STATUS — InvoiceAI v1.0 (2026-09-24)

Attack surface    : ✅  API/UI liées à 127.0.0.1 uniquement ; testé en direct (auth, traversée,
                        injection, upload malveillant, DoS) — aucun contournement trouvé
Authentication    : ✅  Jeton Bearer, comparaison temps constant ; N/A pour MFA/comptes (mono-utilisateur)
Authorization     : ✅  Mass assignment bloqué sur PUT, IDOR testé (UUID malformés → 422)
Secrets           : ✅  Aucun secret en code ni en historique Git (vérifié avant publication) ;
                        Dependabot pas encore activé (⚠️ voir ci-dessous)
Input validation  : ✅  Pydantic + UUID + allowlists ; injection SQL/traversée testées en direct
Dependencies      : ✅  pip-audit 0 vulnérabilité ; ⚠️ scan CVE image Docker non fait (bloqué,
                        nécessite une connexion externe)
Logging           : ✅  Aucun secret dans les logs (vérifié en direct) ; N/A monitoring temps réel
Monitoring        : ➖  N/A pour un outil local mono-utilisateur
Backup/Recovery   : ⚠️  Pas de sauvegarde automatisée ; CACHE_ENCRYPTION_KEY sauvegardée manuellement

Known risks       :
  - Dependabot désactivé sur le repo public — MEDIUM — à activer (gratuit, 1 clic GitHub)
  - Scan CVE OS de l'image Docker non fait — LOW — nécessite une connexion Docker Hub
  - Pas de branch protection sur master — LOW — acceptable en solo, à revoir si collaborateurs

Remaining TODOs   :
  - [ ] Activer Dependabot alerts + security updates
  - [ ] (Optionnel) Scan Trivy en CI pour l'image Docker
  - [ ] (Optionnel) Personnaliser INCIDENT_RESPONSE.md

Décision          : ✅ GO — aucun résultat CRITICAL ou HIGH après tests d'attaque en direct.
                    Voir SECURITY_AUDIT_2026-09-24.md pour le détail complet des tests exécutés.
```
