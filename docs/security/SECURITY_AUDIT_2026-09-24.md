# Security Audit — 2026-09-24

> Audit défensif complet, à jour de la V1.0 publiée (repo public, Docker, CI).
> Combine : relecture des revues P2-P4 déjà faites, tests d'attaque **exécutés en direct**
> contre le vrai serveur (`scripts/run.py`, pas la démo), scans dépendances/SAST relancés,
> vérification des réglages sécurité GitHub.
>
> **Ne modifie aucun code.** Tout ce qui suit a été vérifié par l'exécution, pas supposé —
> sauf mention explicite "non vérifié".

---

## A. Threat Model

Voir [`THREAT_MODEL.md`](THREAT_MODEL.md) (rempli dans le cadre de cet audit — était un
template vide depuis le scaffold P0).

Résumé : outil **mono-utilisateur, local uniquement** (`127.0.0.1`), pas de comptes, pas de
multi-tenant. La menace principale n'est pas "un attaquant distant" (l'API n'écoute nulle
part d'accessible depuis le réseau) mais : (1) un PDF hostile traité par le pipeline, (2) une
sortie LLM non fiable affichée ou exportée, (3) une fuite de secrets locaux (`.env`, cache,
base).

## B. Attack Surface Map

| Surface | Exposition | Testé en direct aujourd'hui |
|---|---|---|
| `POST/GET/PUT/DELETE /invoices`, `/invoices/export.csv` | `127.0.0.1:8000` uniquement | ✅ |
| `/health` | `127.0.0.1:8000`, sans jeton | ✅ |
| Interface Streamlit | `127.0.0.1:8501` (ou `0.0.0.0` interne au conteneur Docker, publié en `127.0.0.1` sur l'hôte) | ✅ (revue P4 + passe navigateur du 22/09) |
| Upload de fichier (PDF) | Via l'API, jeton requis | ✅ |
| Export CSV | Via l'API, jeton requis | ✅ (formules neutralisées) |
| Cache disque + base SQLite | Jamais exposés réseau, chiffrés au repos | ✅ (lecture des octets bruts) |
| `.env` (secrets) | Fichier local uniquement | ✅ (historique Git scanné en entier) |
| Image Docker | Locale, jamais poussée sur un registre public | Scan CVE OS non fait (Docker Scout demande une connexion) |
| Repo GitHub | **Public depuis le 2026-09-24** | ✅ (historique Git scanné avant publication) |
| CI (GitHub Actions) | Déclenchée sur push/PR vers `master` | ✅ (pas de secret réel utilisé) |

**Ce qui n'existe pas dans ce projet** (donc pas de surface correspondante) : pas de
comptes/mots de passe, pas de sessions/cookies, pas de reverse proxy, pas de base de données
accessible depuis Internet, pas de webhook, pas de stockage cloud, pas d'admin séparé.

## C. Security Gaps

Format : Description · Emplacement · Impact · Cause · Correction · Priorité · Vérification

### 1. Dependabot désactivé sur le repo public
- **Emplacement** : réglages GitHub du repo (`Settings > Code security`)
- **Impact** : une CVE future dans une dépendance (FastAPI, cryptography, langchain, etc.) ne sera pas signalée automatiquement
- **Cause** : jamais activé (repo était privé, réglage par défaut)
- **Correction** : activer "Dependabot alerts" + "Dependabot security updates" (gratuit sur repo public, 1 clic)
- **Priorité** : **MEDIUM**
- **Vérification** : `gh api repos/Wade199/invoiceai --jq '.security_and_analysis'` → `dependabot_security_updates.status` doit passer à `"enabled"`

### 2. `docs/security/THREAT_MODEL.md`, `SECURITY_CHECKLIST.md`, `INCIDENT_RESPONSE.md` non remplis
- **Emplacement** : `docs/security/`
- **Impact** : faible en soi (les vraies revues P2-P4 existent et sont sérieuses), mais un lecteur qui ouvre ces fichiers voit des `[NOM DU PROJET]` littéraux — mauvaise impression pour un repo public portfolio
- **Cause** : copiés depuis le template au scaffold, jamais personnalisés
- **Correction** : `THREAT_MODEL.md` et `SECURITY_CHECKLIST.md` remplis dans cet audit (voir ci-dessous). `INCIDENT_RESPONSE.md` reste un gabarit générique correct — à personnaliser si besoin, non prioritaire pour un projet solo sans utilisateurs réels
- **Priorité** : **LOW**
- **Vérification** : lecture des fichiers

### 3. Validation par bit de poids faible sur `Host` (accepté même avec un port fantaisiste ou du texte après)
- **Emplacement** : `starlette.middleware.trustedhost` (dépendance, pas notre code) — comportement `host = headers.get("host","").split(":")[0]`
- **Impact** : `Host: 127.0.0.1:8000@evil.com` ou `Host: 127.0.0.1:8000.evil.com` passent la vérification, car tout ce qui suit le premier `:` est ignoré
- **Cause** : comportement standard de la librairie, pas un bug introduit par nous
- **Correction** : **aucune nécessaire** — un vrai navigateur ne peut pas envoyer un en-tête `Host` avec `@` ou un port suivi de texte arbitraire (rejeté par le navigateur lui-même avant l'envoi) ; le "port" n'est utilisé nulle part ailleurs dans l'app pour une décision de sécurité. Documenté ici pour mémoire, pas pour action
- **Priorité** : **INFO**
- **Vérification** : lu le code source de `starlette/middleware/trustedhost.py` dans `.venv`, testé en direct (voir §Tests exécutés)

### 4. `.env` en permissions `644` (lisible par tout compte local sur la machine)
- **Emplacement** : `.env` à la racine du projet
- **Impact** : sur une machine multi-utilisateurs, un autre compte local pourrait lire les clés. Sur cette machine (poste perso Windows), le risque réel dépend des ACL NTFS du profil utilisateur, pas du mode POSIX affiché par Git Bash
- **Cause** : déjà documenté dans P3_UPLOAD_SECURITY_REVIEW.md / P3_DATABASE_REVIEW.md ("POSIX file modes ne font rien sous Windows")
- **Correction** : aucune action V1 (poste perso mono-utilisateur) ; à revoir si la machine est partagée
- **Priorité** : **LOW** (déjà connu, reconfirmé)
- **Vérification** : `ls -la .env`

### 5. Image Docker jamais scannée pour des CVE au niveau OS (paquets Debian de `python:3.11-slim`)
- **Emplacement** : `Dockerfile`
- **Impact** : une vulnérabilité dans les paquets système de l'image de base ne serait pas détectée automatiquement
- **Cause** : `docker scout` nécessite une connexion Docker Hub, non fournie pendant cet audit (je ne demande jamais tes identifiants)
- **Correction** : lancer `docker scout cves invoiceai:latest` toi-même une fois connecté (`docker login`), ou activer le scan d'image dans GitHub Actions (Trivy en action CI, gratuit) — pas fait ici, proposé en remédiation
- **Priorité** : **LOW** (image jamais publiée sur un registre, usage local uniquement)
- **Vérification** : non vérifiable sans connexion Docker Hub — à faire

### Aucun résultat CRITICAL ou HIGH trouvé

Tous les vecteurs testés en direct (voir §Tests exécutés) ont été correctement bloqués par
les contrôles déjà en place (revues P2-P4). C'est un **résultat positif**, pas une garantie
d'absence totale de faille — voir la section "Limites de cet audit" en bas.

## D. Remediation Plan

| # | Action | Effort | Qui |
|---|---|---|---|
| 1 | Activer Dependabot alerts + security updates (repo public → gratuit) | 2 min, clic GitHub | Ibrahima |
| 2 | (Optionnel) Ajouter un scan Trivy à la CI pour l'image Docker | 30 min | Jarvis, sur demande |
| 3 | (Optionnel) Personnaliser `INCIDENT_RESPONSE.md` pour ce projet précis | 15 min | Jarvis, sur demande |
| 4 | Rien d'autre à corriger dans le code — aucun gap CRITICAL/HIGH | — | — |

## E. Security Checklist

Voir [`SECURITY_CHECKLIST.md`](SECURITY_CHECKLIST.md) (rempli dans le cadre de cet audit).

## F. Security Architecture améliorée

L'architecture actuelle (voir [`architecture.md`](../architecture.md)) est déjà adaptée à la
menace réelle (outil local mono-utilisateur). Aucun changement structurel recommandé pour la
V1. Si le projet évolue vers un usage multi-utilisateur / exposé à Internet (V2, "Option B"
déjà identifiée dans l'historique du projet) :

- Comptes + TLS obligatoires avant toute exposition réseau
- Le jeton Bearer unique deviendrait un jeton par utilisateur (`users` + `user_id`)
- Un reverse proxy (nginx/Caddy) prendrait le TLS, le rate limiting réseau et la protection anti-slowloris (actuellement absents, acceptés en V1 car local)
- Rotation de `CACHE_ENCRYPTION_KEY` (actuellement une seule clé, pas de rotation — `MultiFernet` de la lib `cryptography` le permettrait)

## G. Tests de sécurité à ajouter

La plupart des attaques testées aujourd'hui le sont déjà par la suite automatisée (681
tests). Ce qui **n'est pas** couvert par un test automatisé et a été vérifié seulement
manuellement aujourd'hui :

1. Upload avec `Content-Length` mensonger sur socket brut (testé manuellement, marche — pas
   de test automatisé équivalent)
2. Fichier de 15 Mo réel envoyé en entier (les tests actuels simulent la taille, pas un vrai
   gros fichier sur le disque)
3. Tentative d'injection CRLF sur socket brut (testé manuellement)

Recommandation : ajouter ces 3 cas comme tests d'intégration si le projet grandit ; pas
urgent pour un portfolio V1 (déjà vérifiés une fois, comportement stable et attendu).

---

## Tests exécutés en direct aujourd'hui (contre le vrai serveur, pas mocké)

| Catégorie | Tests | Résultat |
|---|---|---|
| Authentification | Sans jeton, jeton vide, jeton faux (même longueur), jeton tronqué, mauvais schéma (Basic), en-tête dupliqué, jeton en query string, `/docs`/`/redoc`/`/openapi.json` | Tous refusés (401) ou 404 selon le cas — aucun contournement |
| Traversée de chemin | `../../etc/passwd`, encodages URL variés, sur l'ID et sur le nom de fichier uploadé | 404/422 ; aucun fichier écrit hors du dossier prévu (vérifié sur disque) |
| Injection SQL-like | `' OR '1'='1`, `; DROP TABLE`, `UNION SELECT`, `SLEEP()` sur l'ID | 422 avant même d'atteindre la base (validation UUID) |
| UUID malformés | Majuscules, tronqués, trop longs, non-UUID | 422 systématique |
| Upload malveillant | Faux PDF (texte), exécutable renommé, mauvais MIME déclaré, octets `%PDF-` mal placés, fichier vide | 415 systématique, rien écrit sur disque |
| DoS / taille | Fichier 15 Mo réel (limite 10 Mo), `Content-Length` mensonger sur socket brut | 413 en 44ms ; requête malformée traitée sans blocage (422, pas de hang) |
| En-têtes | Injection CRLF (tentative de smuggling sur socket brut), `Host` avec `@`/sous-domaine, `X-Forwarded-Host` | Aucun contournement ; `X-Forwarded-Host` ignoré (non utilisé nulle part) |
| Fuite d'information | Recherche du jeton et de la clé Gemini dans les logs générés pendant toute la session de tests | 0 occurrence |
| Dépendances | `pip-audit` relancé | 0 vulnérabilité connue |
| Analyse statique | `bandit -r src` relancé | 0 problème (4 `#nosec` déjà justifiés) |
| Historique Git | `git log --all -S` sur tous les motifs de clés (Google, Anthropic, GitHub, génériques) avant publication | Aucun secret trouvé |
| Réglages GitHub | Secret scanning, push protection, Dependabot, branch protection | Secret scanning + push protection actifs ; Dependabot désactivé (gap #1) |

## Limites de cet audit

- Pas de scan CVE au niveau OS de l'image Docker (nécessite une connexion Docker Hub)
- Pas de fuzzing automatisé (AFL, etc.) — tests manuels ciblés uniquement
- Pas de test de charge / résistance DDoS réelle (hors sujet pour un outil local mono-utilisateur)
- Le code source a été relu, pas audité ligne par ligne par un second humain
- **Je n'affirme pas que le système est "sécurisé"** — voici les contrôles vérifiés
  ci-dessus et les 5 gaps trouvés (aucun CRITICAL/HIGH), avec leurs limites.
