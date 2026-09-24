# THREAT_MODEL.md — Modèle de menaces

> Projet : InvoiceAI (`assistant-ia-devis-factures`)
> Dernière mise à jour : 2026-09-24
> Statut : Validé (voir [`SECURITY_AUDIT_2026-09-24.md`](SECURITY_AUDIT_2026-09-24.md))

---

## 🎯 Actifs critiques

| Actif | Description | Valeur | Localisation |
|-------|-------------|--------|--------------|
| Données de factures extraites | Fournisseur, montants, lignes — données personnelles/comptables | Confidentiel | Base SQLite (payload chiffré) + cache disque (chiffré) |
| `GOOGLE_API_KEY` | Clé Gemini, quota limité et payant au-delà | Confidentiel | `.env` local uniquement, jamais commité |
| `CACHE_ENCRYPTION_KEY` | Protège la base ET le cache — sa perte rend l'historique illisible | Critique | `.env` local, sauvegardée manuellement par Ibrahima |
| `API_TOKEN` | Seule barrière d'accès à l'API | Élevé | `.env` local |
| PDF uploadé | Contenu potentiellement sensible, mais supprimé juste après traitement | Faible (durée de vie : quelques secondes) | `data/uploads/`, transitoire |

---

## 👥 Utilisateurs & Privilèges

| Rôle | Accès | Niveau de confiance |
|------|-------|---------------------|
| Ibrahima (unique utilisateur) | Accès total à l'app, via le jeton local | Total — pas de séparation de comptes, projet mono-utilisateur assumé |
| Aucun autre utilisateur possible | L'API n'écoute que sur `127.0.0.1` | N/A |

> Pas de modèle multi-utilisateur en V1 (choix assumé, voir `TECHNICAL_DESIGN.md` §4.1 et
> `PROJECT_BRIEF.md`). "Option B" (comptes + TLS) est une piste V2, non implémentée.

---

## 🚪 Points d'entrée

| Point d'entrée | Exposition | Authentification | Validation |
|----------------|------------|-----------------|------------|
| `POST/GET/PUT/DELETE /invoices*` | `127.0.0.1:8000` uniquement | Bearer token (comparaison en temps constant) | Oui — Pydantic + UUID canonique |
| `GET /health` | `127.0.0.1:8000`, sans jeton | Aucune (ne renvoie aucune donnée) | N/A |
| Interface Streamlit | `127.0.0.1:8501` (natif) ou publié en `127.0.0.1:8501` via Docker | Le jeton API est détenu côté serveur (process Streamlit), jamais envoyé au navigateur | `safe()`/`escape_markdown` sur tout texte affiché |
| PDF uploadé | Via l'API uniquement | Jeton requis | Taille ≤10 Mo, MIME `application/pdf` **et** octets `%PDF-`, nom généré par le serveur |
| Google Gemini (sortant) | HTTPS, appel sortant uniquement | Clé API | IBAN/e-mails/téléphones masqués avant envoi |
| `.env` | Fichier local | Permissions OS du profil utilisateur | Jamais suivi par Git (`.gitignore`) |

---

## ⚠️ Menaces identifiées

### CRITICAL

*Aucune identifiée* — l'absence d'exposition réseau (API `127.0.0.1` uniquement) élimine la
plupart des vecteurs habituellement critiques (pas d'accès direct depuis Internet à la base,
pas de surface d'authentification multi-utilisateur à casser).

### HIGH

*Aucune identifiée à ce jour* (voir `SECURITY_AUDIT_2026-09-24.md` §C pour le détail des
tests qui ont mené à cette conclusion — pas une affirmation sans preuve).

### MEDIUM

| # | Menace | Vecteur | Probabilité | Impact | Prévention | Détection | Récupération |
|---|--------|---------|-------------|--------|------------|-----------|--------------|
| T01 | PDF hostile fait planter/ralentit l'extraction | Upload d'un PDF piégé (bombe zip, boucle de rendu, PDF géant) | Faible | Moyen (DoS local) | Taille/pages/temps bornés, parsing dans un sous-processus tuable (P2) | Timeout observable dans les logs | Redémarrer le processus, PDF déjà supprimé |
| T02 | Sortie du LLM non fiable affichée sans échappement | Un PDF fait halluciner Gemini vers du Markdown/HTML actif | Faible (déjà testé, `safe()` bloque) | Moyen si non bloqué | `safe()`/`escape_markdown` sur tout champ venant du LLM (P4) | Test dédié + vérifié en navigateur réel | Aucune (jamais rendu actif) |
| T03 | Perte de `CACHE_ENCRYPTION_KEY` | Erreur humaine, disque corrompu | Faible | Élevé (historique illisible) | Sauvegarde manuelle demandée à Ibrahima | — | Aucune si la clé est perdue (chiffrement fort, par design) |
| T04 | Dependabot désactivé : une CVE future dans une dépendance passe inaperçue | Repo public, aucune alerte automatique | Moyenne (dépendances évoluent) | Variable selon la CVE | À activer (gratuit, 1 clic) | — | `pip-audit` manuel en attendant |

### LOW / INFORMATIONAL

| # | Menace | Vecteur | Notes |
|---|--------|---------|-------|
| T05 | Jeton API en clair dans `.env`, envoyé en clair sur HTTP local | Lecture locale du fichier | Accepté : machine mono-utilisateur, pas de TLS en V1 (documenté, "ne jamais exposer tel quel") |
| T06 | `.env` en permissions `644` | Autre compte local sur la même machine | ACL NTFS réelle du profil Windows fait foi, pas le mode POSIX affiché |
| T07 | Export CSV téléchargé sort du chiffrement/de la rétention de l'app | Fichier sur le disque de l'utilisateur après export | Avertissement affiché dans l'UI à côté du bouton de téléchargement |
| T08 | Image Docker jamais scannée pour des CVE OS | Base `python:3.11-slim` | Usage local uniquement, jamais publiée sur un registre |

---

## 📊 Résumé des risques

| Niveau | Nombre | Statut |
|--------|--------|--------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 4 | 3 déjà mitigées (T01-T03) / 1 à traiter (T04, Dependabot) |
| LOW / INFO | 4 | Acceptées en connaissance de cause (mono-utilisateur, local) |

---

## 🔄 Historique des révisions

| Date | Modification | Auteur |
|------|-------------|--------|
| 2026-09-24 | Rempli à partir du template vide, sur la base de l'audit du même jour + des revues P2-P4 existantes | Jarvis |
