# Projet n°1 — Assistant IA de traitement de devis/factures pour PME

**Durée : 8 semaines.** Le schéma d'architecture a été présenté dans la conversation — ce document en détaille chaque brique, le plan de travail jour par jour, et le plan Figma.

---

## Architecture (rappel des flux)

1. **PME (navigateur)** → upload une facture PDF ou pose une question
2. **API Symfony** → reçoit le fichier, le stocke, orchestre les appels suivants
3. **Extraction de texte / OCR** → transforme le PDF en texte exploitable
4. **Service RAG (FastAPI, Python)** → découpe le texte, l'indexe, retrouve les passages pertinents
5. **Base vectorielle (Chroma)** → stocke les embeddings pour la recherche sémantique
6. **LLM (Claude ou OpenAI API)** → génère la réponse à partir des passages retrouvés
7. **Réponse affichée** → renvoyée à l'utilisateur via l'interface web

Tout, sauf le LLM (externe), tourne dans des conteneurs Docker : `symfony-api`, `rag-service` (FastAPI), `chroma-db`, et une base PostgreSQL pour Symfony.

---

## Plan de travail jour par jour

### Semaine 1 — API Symfony : upload et stockage
- **J1-J2** : `symfony new`, config Docker (PHP-FPM, Nginx, PostgreSQL) via `docker-compose.yml`
- **J3-J4** : entité `Document` (API Platform), endpoint `POST /api/documents` (upload PDF), stockage sur disque + métadonnées en base
- **J5** : tests avec Postman/Insomnia, collection versionnée dans le repo

### Semaine 2 — Extraction de texte / OCR
- **J1-J2** : intégration `Smalot/pdfparser` pour les PDF texte natifs
- **J3-J4** : fallback OCR avec Tesseract (via binding PHP ou appel à un micro-service Python) pour les PDF scannés
- **J5** : endpoint `GET /api/documents/{id}/text`, texte stocké en base, tests sur 5-10 factures réelles/types différents

### Semaine 3 — Pipeline RAG : bases
- **J1-J2** : projet Python (venv), installation LangChain ou LlamaIndex + ChromaDB
- **J3-J4** : script d'indexation (chunking du texte, génération des embeddings)
- **J5** : test manuel — requête simple sur un document indexé

### Semaine 4 — Pipeline RAG : retrieval + génération
- **J1-J2** : chaîne retrieval → prompt → appel LLM (Claude ou OpenAI)
- **J3-J4** : filtrage par `document_id` pour isoler les réponses à une facture précise
- **J5** : jeu de 15-20 questions/réponses de test, mesure du taux de bonnes réponses

### Semaine 5 — Finalisation RAG
- **J1-J2** : gestion des cas limites (document illisible, question hors sujet, absence de réponse)
- **J3-J4** : logs structurés, mesure de la latence par requête
- **J5** : documentation technique du pipeline (README dédié au service RAG)

### Semaine 6 — API FastAPI
- **J1-J2** : wrapper FastAPI (`POST /index`, `POST /ask`) autour du pipeline
- **J3-J4** : clé API interne pour sécuriser l'appel Symfony → FastAPI, `Dockerfile` du service
- **J5** : tests d'intégration Symfony ↔ FastAPI (appel HTTP réel entre conteneurs)

### Semaine 7 — Intégration + interface
- **J1-J2** : endpoint Symfony qui relaie une question vers FastAPI et retourne la réponse
- **J3-J4** : interface web (basée sur les maquettes Figma — voir plus bas) : upload + zone de question/réponse
- **J5** : tests bout en bout (upload → indexation → question → réponse affichée)

### Semaine 8 — Déploiement + présentation
- **J1-J2** : `docker-compose.yml` complet (Symfony + FastAPI + Chroma + PostgreSQL + Nginx), déploiement sur Railway/Render ou un VPS
- **J3** : README principal (architecture, installation, captures d'écran)
- **J4** : vidéo de démo (2-3 min)
- **J5** : publication GitHub (repo public, code propre) + publication LinkedIn

---

## Plan Figma (maquettes de l'interface)

**Organisation du fichier Figma :**
- Page 1 — "Wireframes" (basse fidélité, structure uniquement)
- Page 2 — "UI Kit" (couleurs, typographie, composants réutilisables : bouton, champ, carte, badge de statut)
- Page 3 — "Écrans finaux" (haute fidélité)
- Page 4 — "Prototype" (liens entre écrans pour la démo cliquable)

**Écrans à concevoir (dans l'ordre du parcours utilisateur) :**

1. **Accueil / Upload** — zone de dépôt de fichier PDF, liste des formats acceptés, bouton "Analyser"
2. **Liste des documents** — tableau ou cartes avec statut (`en cours`, `traité`, `erreur`), date, nom du fichier
3. **Détail d'un document** — aperçu du PDF à gauche, zone de question/réponse (chat) à droite
4. **Interface de question/réponse** — champ de saisie, historique des questions posées, réponse de l'IA avec référence au passage source
5. **Dashboard simple** — nombre de documents traités, temps moyen de traitement, taux de réponses réussies (bon pour la démo recruteur)

**Recommandations de style :**
- Palette sobre et professionnelle (bleu/gris/blanc — cohérent avec un outil B2B PME), un accent de couleur pour les statuts (vert = traité, orange = en cours, rouge = erreur)
- Typographie simple (Inter ou Roboto), hiérarchie claire entre titres et texte
- Composants réutilisables dès le départ (bouton, champ, carte) pour accélérer la suite (projet n°2)

**Méthode de travail conseillée :**
1. Wireframes basse fidélité pour les 5 écrans (1-2h, pour valider la structure avant de perdre du temps sur le détail visuel)
2. UI Kit minimal (couleurs + typographie + 4-5 composants)
3. Écrans haute fidélité à partir du kit
4. Prototype cliquable (upload → liste → détail → question/réponse) pour la vidéo de démo

---

*Ce plan s'appuie sur ton stack existant (Symfony/API Platform) et prépare directement le projet n°2 (MVP SaaS multi-tenant) qui réutilisera cette même base UI.*
