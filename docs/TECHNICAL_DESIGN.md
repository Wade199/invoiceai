# Technical Design — InvoiceAI

> **Document technique vivant.** Rempli au fur et à mesure des étapes P1 → P5.
> Contient les **contrats des modules**, décisions de design local, schémas de données.
>
> **Différent de** :
> - `PROJECT_BRIEF.md` → le "pourquoi" (business, scope, contraintes)
> - `docs/architecture_assistant_ia_factures.svg` → la vue macro (composants + flux)
> - `docs/adr/` → les décisions structurantes (1 fichier = 1 décision)
> - `docs/wireframes.md` → l'UI

---

## 📋 Méthode — Design juste-à-temps

On design **1 module à la fois**, **juste avant** de le coder :

1. **Contrat** = signatures des fonctions/classes publiques (entrée, sortie, erreurs).
2. **Choix de design locaux** = décisions internes au module + le "pourquoi".
3. **Points d'incertitude** = ce qu'on ne sait pas encore et qu'on découvrira en codant.

**Règle** : si on apprend quelque chose en codant → on revient corriger ce doc. C'est **normal**, c'est même **souhaité**. Un doc figé qui ne reflète plus la réalité est pire qu'un doc vivant qui bouge.

---

## 🧭 Sommaire

### Standards transverses (s'appliquent à tous les modules)
- [🎯 Conventions de code](#-conventions-de-code)
- [⚠️ Hiérarchie d'exceptions](#️-hiérarchie-dexceptions)
- [🧪 Stratégie de tests](#-stratégie-de-tests)

### Modules

| # | Module | Statut | Étape |
|---|--------|--------|-------|
| 1 | [Module OCR — Extraction de texte PDF](#1-module-ocr-) | ✅ Validé | P1 (implémentation en cours) |
| 2 | [Module LLM — Extraction structurée (Gemini)](#2-module-llm-) | ⬜ | P2 |
| 3 | [Modèle de données — Schéma SQLite](#3-modèle-de-données-) | ⬜ | P2/P3 |
| 4 | [Module API — Endpoints FastAPI](#4-module-api-) | ⬜ | P3 |
| 5 | [Module UI — Streamlit](#5-module-ui-) | ⬜ | P4 |

Légende : ⬜ vide · ⏳ en cours · ✅ rempli et validé

---

## 🎯 Conventions de code

Standards appliqués à **tout le code Python** du projet.

### Style
- **Formatage** : `ruff format` (config dans `pyproject.toml`)
- **Linting** : `ruff check` — 0 warning avant chaque commit
- **Import order** : géré par `ruff` (isort compatible)

### Typage
- **Type hints obligatoires** sur toutes les fonctions publiques (paramètres + retour)
- `from __future__ import annotations` en tête de chaque fichier (compat Python 3.11+)
- `X | None` au lieu de `Optional[X]` (syntaxe moderne)

### Docstrings
- Style **Google** (choisi pour sa lisibilité et son support dans les IDE)
- Docstring **obligatoire** sur : fonctions publiques, classes, méthodes publiques
- Docstring **optionnel** sur : méthodes privées (`_snake_case`), fonctions triviales <5 lignes

Exemple :

```python
def extract_text_from_pdf(pdf_path: Path) -> ExtractedDocument:
    """Extract text content from a PDF invoice file.

    Args:
        pdf_path: Absolute path to the PDF file to process.

    Returns:
        ExtractedDocument containing text, page count, and warnings.

    Raises:
        PDFCorruptedError: If the file cannot be opened as a PDF.
        EmptyDocumentError: If the PDF contains no extractable text.
    """
```

### Naming
- `snake_case` : fonctions, variables, modules, fichiers
- `PascalCase` : classes, exceptions
- `UPPER_CASE` : constantes de module
- **Préfixe `_`** : membres privés (convention Python, pas d'enforcement)

### Autres
- **1 classe = 1 fichier** dès que la classe fait > 50 lignes
- **Pas de `print()`** en dehors des scripts CLI → utiliser `logging`
- **Pas de secrets en dur** → toujours via `os.getenv(...)` ou `python-dotenv`
- **F-strings** partout (pas de `%` ni de `.format()`)

---

## ⚠️ Hiérarchie d'exceptions

Toutes les exceptions custom héritent d'une racine commune (`InvoiceAIError`). Ça permet aux couches hautes (API, UI) de faire un `try/except InvoiceAIError` global sans devoir connaître toutes les sous-classes.

**Fichier** : `src/core/exceptions.py`

### Arbre

```
InvoiceAIError (racine — tous les modules)
├── OCRError (module OCR — P1)
│   ├── PDFCorruptedError       # PDF illisible / mal formé
│   ├── EmptyDocumentError      # PDF valide mais sans texte extractible
│   └── UnsupportedPDFError     # PDF scanné image (V1 ne gère pas)
│
├── LLMError (module LLM — P2)
│   ├── ExtractionFailedError   # LLM a répondu mais parsing JSON KO
│   ├── RateLimitError          # Quota Gemini atteint (15 req/min free)
│   └── ProviderTimeoutError    # Gemini timeout
│
├── ValidationError (module validation — P2)
│   └── InconsistentTotalsError # HT + TVA ≠ TTC (tolérance ±0.02 €)
│
├── StorageError (module DB — P3)
│   ├── DuplicateInvoiceError   # SHA-256 déjà en base
│   └── InvoiceNotFoundError    # ID inexistant
│
└── APIError (module API — P3)
    ├── FileTooLargeError       # > 10 Mo
    └── InvalidFileTypeError    # MIME ≠ application/pdf
```

### Règles
- **Chaque exception embarque un message clair** (destiné aux logs, pas à l'utilisateur final)
- **Traduction utilisateur** = responsabilité de la couche UI, pas des modules métier
- **Ne pas hiérarchiser trop profond** : max 2 niveaux au-dessus de la racine

### Squelette minimal

```python
# src/core/exceptions.py
class InvoiceAIError(Exception):
    """Base exception for all InvoiceAI errors."""

class OCRError(InvoiceAIError):
    """Base for OCR module errors."""

class PDFCorruptedError(OCRError):
    """Raised when a PDF file cannot be parsed."""
```

*Les sous-classes seront ajoutées au fur et à mesure des modules P1 → P3.*

---

## 🧪 Stratégie de tests

**Framework** : `pytest` + `pytest-cov` (déjà dans `requirements.txt`).

### 3 types de tests

| Type | Dossier | Quoi | Vitesse | Marker pytest |
|------|---------|------|---------|---------------|
| **Unit** | `tests/unit/` | 1 fonction ou classe, dépendances mockées | Rapide (<100 ms) | (défaut) |
| **Integration** | `tests/integration/` | Plusieurs modules ensemble, SQLite en mémoire | Moyen (<2 s) | `@pytest.mark.integration` |
| **LLM (slow)** | `tests/slow/` | Appel réel à Gemini | Lent (>2 s) | `@pytest.mark.slow` |

- **Développement quotidien** : `pytest -m "not slow"` (rapide, offline)
- **Avant merge / release** : `pytest` (tout, incluant `slow`)

### Fixtures partagées

**Fichier** : `tests/conftest.py`

Fixtures à prévoir :
- `sample_invoice_pdf` → chemin vers 1 PDF dans `tests/fixtures/pdfs/`
- `sample_invoice_data` → dict de données attendues pour ce PDF (**vérité terrain**)
- `tmp_db` → SQLite en mémoire, propre à chaque test
- `mock_gemini_response` → réponse Gemini pré-enregistrée pour éviter les vrais appels

### Mocks Gemini

**Règle** : les tests unit **ne doivent jamais** appeler l'API Gemini (coût, flakiness, offline).

- Les vraies réponses Gemini sont **enregistrées** dans `tests/fixtures/gemini_responses/*.json`
- Rejouées via `pytest-mock` (`monkeypatch` du client Gemini)
- Seuls les tests `@pytest.mark.slow` appellent vraiment l'API

### Coverage cible

- **Objectif V1** : ≥ **70 %** sur `src/` (excluant `src/ui/` — Streamlit teste mal)
- **Vérifié en CI** (P5) : échec du build si coverage < 70 %
- **Rapport local** : `pytest --cov=src --cov-report=term-missing`

### Ce qu'on **ne teste PAS** en V1
- L'UI Streamlit (test manuel + screenshots)
- La **qualité** des prompts LLM (on teste le **parsing** de la réponse, pas la pertinence)
- Le format visuel des exports CSV/Excel (juste la présence des colonnes attendues)

---

## 1. Module OCR 📄

**Rôle** : lire un PDF de facture/devis et retourner le **texte brut**, prêt pour le LLM (module 2).
**Fichier** : `src/ocr/extractor.py`
**Statut** : ✅ Contrat validé (V1) — implémentation en cours

### 1.1 Interface publique

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ExtractedDocument:
    """Résultat d'une extraction OCR sur un PDF.

    Attributes:
        text: Texte concaténé de toutes les pages, séparé par
            "\n\n---PAGE {n}---\n\n" entre chaque page.
        page_count: Nombre total de pages du PDF.
        warnings: Messages non-bloquants
            (ex: "page 2 sans texte", "PDF de 15 pages, performance dégradée").
        source_file: Chemin absolu du PDF source (traçabilité).
        metadata: Métadonnées PDF brutes (auteur, date création, producteur…).
    """
    text: str
    page_count: int
    source_file: Path
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


def extract_text_from_pdf(pdf_path: Path) -> ExtractedDocument:
    """Extract text content from a PDF invoice/quote file.

    Args:
        pdf_path: Absolute path to the PDF file to process.

    Returns:
        ExtractedDocument containing text, page count, warnings, and metadata.

    Raises:
        FileNotFoundError: If pdf_path does not exist (Python natif, non wrappé).
        PDFCorruptedError: If the file cannot be opened as a valid PDF.
        EmptyDocumentError: If the PDF is valid but contains zero extractable text.
        UnsupportedPDFError: If the PDF appears to be a scanned image (no text layer).
    """
    ...
```

### 1.2 Choix de design (et les "pourquoi")

| # | Choix | Décision | Pourquoi |
|---|-------|----------|----------|
| 1 | **Fonction pure vs classe** | Fonction (`extract_text_from_pdf`) | Stateless, simple à tester, pas de config à porter |
| 2 | **Type du chemin** | `Path` obligatoire (pas `str`) | Type-safe, évite les bugs de séparateurs Windows/Linux |
| 3 | **Détection PDF scanné** | Si `len(text.strip()) < 100` → `UnsupportedPDFError` | Un PDF scanné retourne peu/pas de texte via pdfplumber. Seuil à valider empiriquement. |
| 4 | **Séparateur multi-pages** | `\n\n---PAGE {n}---\n\n` | Aide le LLM à comprendre la structure (utile pour factures 2-3 pages) |
| 5 | **Extraction des tables** | **V1 : intégrées au texte via `.extract_text()`** | Simple, on laisse le LLM se débrouiller. Si résultat pauvre en P2 → passer à `.extract_tables()` en V1.1 |
| 6 | **Nettoyage du texte** | `strip()` par page + normalisation `\s+` → ` ` | Réduit le bruit sans casser la structure |
| 7 | **Immutabilité** | `@dataclass(frozen=True)` | Empêche les modifs accidentelles après extraction |
| 8 | **Logging** | `logger.info` début/fin extraction, `logger.warning` par warning ajouté | Traçabilité pour debug + observabilité future |
| 9 | **PDF encryptés** | Traités comme `PDFCorruptedError` en V1 (pas d'exception dédiée) | Rare en facturation PME, à raffiner si un utilisateur remonte le cas |

### 1.3 Comportement attendu

**Cas nominal (99 % du temps V1)** :
- PDF texte natif (généré par Word / Excel / logiciel de facturation)
- 1 à 3 pages
- `extract_text_from_pdf()` retourne un `ExtractedDocument` avec `text` non vide et `warnings=[]`

**Cas d'erreur (levée d'exception)** :

| Situation | Exception |
|-----------|-----------|
| Fichier n'existe pas | `FileNotFoundError` (Python natif) |
| Fichier existe mais pas un PDF valide | `PDFCorruptedError` |
| PDF valide, mais 0 caractère extractible sur toutes les pages | `EmptyDocumentError` |
| PDF valide, mais `< 100 chars` extraits (probablement scan image) | `UnsupportedPDFError` |
| PDF encrypté / protégé par mot de passe | `PDFCorruptedError` (V1) |

**Warnings (non-bloquants, ajoutés à `ExtractedDocument.warnings`)** :
- Une page individuelle est vide → `"page {n} sans texte extractible"`
- Le PDF a plus de 10 pages → `"PDF long ({n} pages), extraction complète mais performance dégradée"`

### 1.4 Points d'incertitude (à trancher en codant P1)

- [x] **Seuil "PDF scanné" à 100 chars** — validé sur les 5 fixtures réelles (304 à 359 chars chacune, large marge) et sur `tests/fixtures/pdfs/short_text.pdf` (10 chars). Reste arbitraire pour de vrais PDF utilisateurs très courts (1 ligne) — à réajuster si des faux positifs apparaissent en usage réel.
- [x] **Extraction des tables** — validé : `pdfplumber.extract_text()` reconstitue correctement les lignes de facture car les colonnes sont dessinées à la même hauteur `y` dans nos PDF (`reportlab`). Pas besoin de `.extract_tables()` en V1. À réévaluer si des PDF réels (autre logiciel de facturation) cassent l'alignement.
- [x] **Encodage** — vérifié : `pdfplumber` extrait correctement les accents (testé sur `Labbé`, code point `0xE9` confirmé). Le `�` observé pendant les tests manuels était un artefact d'affichage du terminal Windows (codepage), pas une corruption des données.
- [x] **Métadonnées PDF** — gardé en V1 (`metadata: dict[str, str]`, coût nul, déjà dans le contrat validé). Aucun consommateur défini pour l'instant (LLM/DB arrivent en P2/P3) — à retirer si toujours inutilisé fin P3.

### 1.5 Ce qui est **hors scope** de ce module

- ❌ OCR d'images (Tesseract, EasyOCR) → V2
- ❌ Détection de langue → responsabilité du LLM (module 2)
- ❌ Parsing structuré (montants, dates, fournisseur) → responsabilité du LLM (module 2)
- ❌ Persistance en base → responsabilité du module Storage (module 3)

---

## 2. Module LLM 🤖

**Rôle** : envoyer le texte extrait à Gemini et récupérer les données structurées (fournisseur, dates, montants, lignes), avec validation métier et cache.
**Statut** : ⏳ En cours — sous-module 2.1 (schémas) implémenté, le reste à venir

### 2.1 Schémas de données — `src/models/schemas.py` ✅

```python
class InvoiceLineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    total: float


class ExtractedInvoice(BaseModel):
    invoice_number: str | None = None
    date: str | None = None          # ISO 8601 (YYYY-MM-DD)
    supplier: str | None = None
    client: str | None = None
    lines: list[InvoiceLineItem] = []
    subtotal_ht: float | None = None
    tva_rate: float | None = None
    total_ttc: float | None = None
    extraction_confidence: Literal["high", "low"] = "high"
    warnings: list[str] = []
```

**Choix de design** :
| # | Choix | Décision | Pourquoi |
|---|-------|----------|----------|
| 1 | Tous les champs métier `\| None` | Le LLM peut retourner `null` plutôt qu'inventer une valeur (garde-fou anti-hallucination, cf. `PROJECT_BRIEF.md` §5.5) |
| 2 | `Pydantic BaseModel` (pas dataclass) | Nécessaire pour `PydanticOutputParser` de LangChain (§2.2) — validation + parsing JSON automatique |
| 3 | `extraction_confidence: Literal["high","low"]` | Posé par le LLM par défaut à `"high"`, repassé à `"low"` par le module de validation (§2.3) si incohérence détectée — pas d'exception levée, juste un flag consommé par l'UI |
| 4 | Pas de champ `currency` en V1 | Hors scope V1 (`PROJECT_BRIEF.md` §9 — multi-devises reporté en V2) |

### 2.2 Adapter Gemini — `src/llm/gemini_adapter.py` ✅

**Implémenté** : `extract_invoice_data(document: ExtractedDocument) -> ExtractedInvoice`

**Choix de design** :
| # | Choix | Décision | Pourquoi |
|---|-------|----------|----------|
| 1 | `llm.with_structured_output(ExtractedInvoice)` plutôt que `PydanticOutputParser` manuel | Structured output natif de Gemini (function calling) — plus fiable qu'un parsing JSON texte fait à la main, moins de code |
| 2 | Retry via `tenacity` sur `RateLimitError` + `ProviderTimeoutError` uniquement (pas `ExtractionFailedError`) | Erreurs transitoires (quota, indispo réseau) valent la peine d'être retentées ; un JSON malformé est un problème de prompt/schéma, pas résolu par un retry aveugle |
| 3 | `_build_structured_llm()` isolée dans sa propre fonction | Permet de la monkeypatcher dans les tests sans mocker les internals de `langchain`/`google-genai` |
| 4 | Backoff exponentiel `wait_exponential(multiplier=2, min=2, max=10)`, 3 tentatives max | Cohérent avec le rate limit Gemini (15 req/min = ~1 req/4s) sans faire attendre l'utilisateur trop longtemps |
| 5 | `google.genai.errors.ClientError`/`ServerError` distingués par `.code` (429 → `RateLimitError`, autre 4xx → `ExtractionFailedError`, 5xx → `ProviderTimeoutError`) | Mapping direct des codes HTTP Gemini vers notre hiérarchie d'exceptions métier |

**Erreurs (corrigé après revue sécurité)** : `langchain-google-genai` re-lève les erreurs HTTP sous ses propres classes (`GoogleRateLimitError`, `GoogleAuthenticationError`…) qui **ne sont pas** des `ClientError`. Mapping actuel : 429 → `RateLimitError` (retry), 401/403 → `LLMAuthError` (jamais retry), autres 4xx → `ExtractionFailedError` (message sans le corps de la réponse), 5xx → `ProviderTimeoutError`. Clé absente → `LLMAuthError` (fail closed) ; `load_dotenv()` ne remplace pas les variables déjà définies. Voir `docs/security/P2_SECURITY_REVIEW.md`.

**Prompt** : documenté séparément dans `docs/prompt_engineering.md` (garde-fous "if unsure, return null" + 1 exemple few-shot). **Testé et validé sur 5/5 factures fictives (100% de précision)**.

**Tests** : `tests/unit/test_gemini_adapter.py`, 5 tests, aucun appel réel à Gemini (`_build_structured_llm` monkeypatché + `tenacity.nap.time.sleep` neutralisé pour éviter les vrais délais de retry en test).

### 2.3 Validation métier — `src/services/validate_invoice.py` ✅

**Contrat prévu** : `validate_invoice(invoice: ExtractedInvoice) -> ExtractedInvoice`
- Règle 1 : `sum(line.total for line in lines) ≈ subtotal_ht` (tolérance ±0,02 €)
- Règle 2 : `subtotal_ht × (1 + tva_rate) ≈ total_ttc` (tolérance ±0,02 €)
- Ne lève pas d'exception → passe `extraction_confidence = "low"` + ajoute un message dans `warnings` si incohérence

**Implémenté** : 3 règles (ajout d'une règle 0 : `quantity × unit_price ≈ total` par ligne). Une règle est **ignorée** si une de ses entrées est `null` (un `null` du LLM est une réponse légitime, pas une incohérence). Fonction pure : retourne une copie (`model_copy`), l'entrée n'est pas mutée, les `warnings` existants sont conservés.

| # | Choix | Pourquoi |
|---|-------|----------|
| 1 | Écart arrondi au centime avant comparaison | Bug trouvé par les tests : `abs(60.02 - 60.0)` = `0.0200000000000031` > 0.02 en float. `Decimal` écarté en V1 (le schéma est en `float`) |
| 2 | Tolérance absolue 0,02 € | Couvre l'arrondi ligne par ligne ; pas de tolérance relative en V1 |

**Incertitude ouverte** : `tva_rate` attendu en fraction (0.20). Si le LLM renvoie 20, la règle 3 lèvera un warning (faux positif visible, pas silencieux) — à surveiller sur factures réelles.

**Tests** : `tests/unit/test_validate_invoice.py`, 12 cas, 100 % de couverture du module.

### 2.4 Cache SHA-256 — `src/services/cache.py` ✅

**Contrat prévu** :
- `get_cached(pdf_hash: str) -> ExtractedInvoice | None`
- `store_cache(pdf_hash: str, invoice: ExtractedInvoice) -> None`
- Clé = SHA-256 du contenu binaire du PDF (évite de rappeler Gemini sur un fichier déjà traité)

**Implémenté** : `hash_pdf(path)`, `get_cached(hash)`, `store_cache(hash, invoice)`, `delete_cached(hash)` (ajouté pour le RGPD : le cache contient des données de facture).

| # | Choix | Pourquoi |
|---|-------|----------|
| 1 | 1 fichier JSON par hash dans `CACHE_DIR` (défaut `data/cache/`, gitignoré) | Le brief autorise « mémoire ou disque » ; le disque survit aux redémarrages Streamlit, sans dépendre de SQLAlchemy (pas encore en place). Migrable vers SQLite en P3 sans changer les 3 signatures |
| 2 | Hash validé (`[0-9a-f]{64}`) avant de devenir un nom de fichier | Empêche le path traversal si un appelant passe une valeur venant de l'utilisateur |
| 3 | Entrée corrompue / schéma obsolète = miss + suppression, pas d'exception | Pire cas = 1 appel Gemini de plus, jamais un crash |
| 4 | Écriture atomique (fichier temporaire puis `os.replace`) | Un crash en cours d'écriture ne laisse jamais un JSON tronqué |
| 5 | Erreurs d'E/S = `StorageError` (nouvelle branche de la hiérarchie) | Cohérent avec la hiérarchie `InvoiceAIError` |

**Pas de TTL en V1** : la rétention RGPD (30 j) sera gérée avec la base en P3 ; d'ici là `delete_cached()` permet la suppression à la demande. Si le schéma `ExtractedInvoice` change, les anciennes entrées invalides sont ignorées, mais des entrées valides mais obsolètes (ex. prompt amélioré) resteraient servies : vider `data/cache/` après un changement de prompt.

**Tests** : `tests/unit/test_cache.py`, 13 cas (dossier temporaire via `CACHE_DIR`, aucun appel réseau).

### 2.5 Orchestration — `src/services/pipeline.py` ✅

**Contrat** : `process_invoice(pdf_path: Path) -> ExtractedInvoice` — hash → cache → OCR → Gemini → validation → écriture cache.

- Le résultat **validé** est mis en cache (un hit saute OCR, Gemini et validation). Si les règles de validation ou le prompt changent, vider `data/cache/`.
- Aucune exception n'est attrapée : elles remontent (`OCRError`, `LLMError`, `StorageError`) et l'API/UI les traduit.
- Une extraction en erreur n'est jamais mise en cache.
- **Tests** : `tests/integration/test_pipeline.py` (marker `integration`, Gemini remplacé par un faux compteur d'appels) — vérifie facture valide, montants incohérents → `low`, 2ᵉ appel sans Gemini, erreur OCR propagée.

---

## 3. Modèle de données 🗃

**Rôle** : schéma SQLite pour persister les factures traitées.

**Fichier** : `src/models/invoice.py` + migrations.

*Section vide — sera remplie à P2/P3.*

---

## 4. Module API 🌐

**Rôle** : exposer les endpoints REST utilisés par l'UI.

**Fichier** : `src/api/routes.py`

*Section vide — sera remplie à P3.*

---

## 5. Module UI 🖥

**Rôle** : interface Streamlit pour uploader, visualiser, corriger, exporter.

**Fichier** : `src/ui/app.py`

*Section vide — sera remplie à P4.*

---

## 📝 Journal des mises à jour

| Date | Section | Changement |
|------|---------|------------|
| 2026-09-18 | Init | Création du squelette |
| 2026-09-18 | Standards transverses | Ajout Conventions de code + Hiérarchie d'exceptions + Stratégie de tests |
| 2026-09-18 | Module OCR | Ajout du contrat V1 (ébauche en review) |
