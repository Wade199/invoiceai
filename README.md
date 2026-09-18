# InvoiceAI

> AI-powered extraction of structured data (supplier, dates, amounts, line items)
> from PDF invoices and quotes, exported to CSV/Excel.

Portfolio project by [Ibrahima](https://github.com/) — built while transitioning
from Junior PHP/Symfony developer to AI Software Engineer.

**Status**: 🚧 P0 — scaffold in progress. See [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md) for the full spec.

---

## What it does

Upload a PDF invoice/quote → the app extracts the supplier, dates, HT/VAT/TTC
amounts and line items via a Gemini-powered LLM pipeline, validates the numbers
for consistency (LLMs hallucinate), and lets you export the result to CSV.

## Stack (V1)

| Layer | Tech |
|---|---|
| Language | Python 3.11+ |
| LLM | Google Gemini (`gemini-flash-latest`) via `langchain-google-genai` |
| PDF text extraction | `pdfplumber` |
| API | FastAPI + Pydantic v2 |
| Database | SQLite + SQLAlchemy 2.x |
| UI | Streamlit |
| Tests | `pytest` |
| Lint/format | `ruff` |

No Docker / CI in V1 — deliberately kept lean for a portfolio MVP (see
[`PROJECT_BRIEF.md`](PROJECT_BRIEF.md) §4 and §9 for the reasoning). Both are
planned for the P5 phase.

## Getting started

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

copy .env.example .env        # then fill in GOOGLE_API_KEY
python scripts/generate_fake_invoices.py   # generate 5 test PDFs in data/fake_invoices/

make dev                      # run the Streamlit UI
make test                     # run tests
make lint                     # ruff check + format check
```

## Security & GDPR

This project handles invoice data (personal + accounting data). Non-negotiable
controls (see [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md) §5):

- Upload validation: max 10 MB, `application/pdf` MIME only
- Configurable data retention (`DEFAULT_RETENTION_DAYS`) + `DELETE /invoice/{id}`
- LLM output validated against arithmetic consistency rules before being trusted
- Rate limiting + exponential backoff on the Gemini free tier (15 req/min)

Full checklist: [`docs/security/SECURITY_CHECKLIST.md`](docs/security/SECURITY_CHECKLIST.md)

## Project docs

- [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md) — full V1.0 spec (source of truth)
- [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) — living architecture/decisions doc
- [`TASKS.md`](TASKS.md) — phase-by-phase backlog
- [`DECISIONS.md`](DECISIONS.md) — decision log
- [`projet-1-assistant-ia-factures.md`](projet-1-assistant-ia-factures.md) — original early-stage planning notes (superseded by `PROJECT_BRIEF.md`)

## License

Portfolio project — not licensed for commercial reuse.
