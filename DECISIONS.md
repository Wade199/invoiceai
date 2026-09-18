# DECISIONS.md — Registre des décisions

> Décisions majeures documentées ici. Le détail complet du cadrage V1 est dans PROJECT_BRIEF.md.

---

## Format d'une décision

```
### [DATE] — [Titre de la décision]

**Contexte** : Pourquoi cette décision était nécessaire
**Options considérées** :
  - Option A : [description] → Avantages / Inconvénients
  - Option B : [description] → Avantages / Inconvénients
**Décision** : Option choisie et pourquoi
**Conséquences** : Ce que ça implique pour la suite
**Statut** : Validée / En discussion / Révisée
```

---

## Décisions

### 2026-09-18 — LLM principal = Google Gemini (pas Claude/OpenAI)

**Contexte** : Le pipeline d'extraction a besoin d'un LLM multimodal capable de lire du PDF/image directement.

**Options considérées** :
- Option A : Anthropic Claude → Meilleure qualité perçue, mais le compte Console d'Ibrahima n'a aucun free tier (nécessite des crédits payants achetés, `credit balance is too low`)
- Option B : Google Gemini → Free tier officiel sans carte bancaire, multimodal natif (PDF/images en input direct)

**Décision** : Option B (Gemini, `gemini-flash-latest` via `langchain-google-genai`)

**Conséquences** : Architecture pensée provider-agnostic (LangChain) pour pouvoir switcher vers Claude/GPT en V2 sans refactoring majeur.

**Statut** : Validée — `GOOGLE_API_KEY` testée et fonctionnelle (appel réel réussi, 0 USD)

---

### 2026-09-18 — Stack V1 volontairement allégée

**Contexte** : Un premier prompt de cadrage était trop ambitieux/générique (Docker+CI dès P0, multi-fallback OCR, `uv`, coverage 70%+ imposé...).

**Options considérées** :
- Option A : Stack complète dès le départ → Plus "pro" sur le papier, mais alourdit le démarrage et retarde le premier résultat démontrable
- Option B : Stack minimale V1 (pip, pdfplumber seul, Streamlit natif, sans Docker/CI), V2 en itération ultérieure

**Décision** : Option B — voir PROJECT_BRIEF.md §9 pour la liste complète des éléments retirés et leur justification

**Conséquences** : Docker + CI + PostgreSQL + provider-agnostic reportés à P5/V2. Focus V1 = pipeline IA qui fonctionne + code propre + démonstrable en entretien.

**Statut** : Validée

---

### 2026-09-18 — Méthode de collaboration : pair programming (pas de génération 100% par IA)

**Contexte** : Un projet 100% généré par Jarvis est contre-productif : zéro apprentissage pour Ibrahima et détectable/impossible à défendre en entretien technique.

**Options considérées** :
- Option A : Jarvis génère tout le code → rapide, mais Ibrahima ne peut pas l'expliquer ligne par ligne
- Option B : Pair programming — Jarvis génère le boilerplate sans valeur pédagogique (P0, P5), Ibrahima code lui-même le cœur métier (P1-P4) avec coaching de Jarvis

**Décision** : Option B

**Conséquences** : P1-P4 seront plus lents mais Ibrahima doit pouvoir expliquer chaque ligne de `src/ocr`, `src/llm`, `src/services`, `src/api` en entretien.

**Statut** : Validée

---

<!-- Ajouter les décisions au fur et à mesure -->
