from __future__ import annotations

import logging
import os

from google.genai.errors import ClientError, ServerError
from langchain_google_genai import ChatGoogleGenerativeAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.core.exceptions import ExtractionFailedError, ProviderTimeoutError, RateLimitError
from src.models.schemas import ExtractedInvoice
from src.ocr.extractor import ExtractedDocument

logger = logging.getLogger(__name__)

_MODEL_NAME = "gemini-flash-latest"
_MAX_ATTEMPTS = 3
_RATE_LIMIT_HTTP_CODE = 429

_EXTRACTION_PROMPT_TEMPLATE = """\
You are an expert at extracting structured data from French business invoices \
and quotes (factures/devis).

Extract these fields from the invoice text below:
- invoice_number: the invoice/quote reference number
- date: the invoice date, normalized to ISO 8601 (YYYY-MM-DD)
- supplier: the name of the company issuing the invoice
- client: the name of the company or person being billed
- lines: each line item (description, quantity, unit_price HT, total HT)
- subtotal_ht: total excluding tax (HT)
- tva_rate: the VAT rate as a decimal (e.g. 0.20 for 20%)
- total_ttc: total including tax (TTC)

Rules:
- If a value is missing, ambiguous, or you are not confident about it, return
  null for that field. NEVER guess or invent a value.
- Amounts are numbers (dot as decimal separator), not strings.
- Normalize dates to ISO 8601 even if written differently in the source
  (e.g. "24/02/2026" -> "2026-02-24").

Example:
Input:
FACTURE INV-001
Date: 15/03/2026
Fournisseur: Acme SARL
Client: Dupont
Description Qte PU HT Total HT
Conseil 2 100.00 200.00
Sous-total HT: 200.00
TVA (20%): 40.00
Total TTC: 240.00

Output fields:
invoice_number="INV-001", date="2026-03-15", supplier="Acme SARL", client="Dupont",
lines=[{{"description": "Conseil", "quantity": 2, "unit_price": 100.0, "total": 200.0}}],
subtotal_ht=200.0, tva_rate=0.20, total_ttc=240.0

Now extract the data from this invoice:
{text}
"""


def _build_structured_llm():
    """Build the Gemini chat model bound to the ExtractedInvoice schema.

    Isolated in its own function so tests can monkeypatch it instead of
    mocking the langchain/google-genai internals directly.
    """
    llm = ChatGoogleGenerativeAI(model=_MODEL_NAME, google_api_key=os.getenv("GOOGLE_API_KEY"))
    return llm.with_structured_output(ExtractedInvoice)


@retry(
    retry=retry_if_exception_type((RateLimitError, ProviderTimeoutError)),
    stop=stop_after_attempt(_MAX_ATTEMPTS),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    reraise=True,
)
def extract_invoice_data(document: ExtractedDocument) -> ExtractedInvoice:
    """Send extracted OCR text to Gemini and parse the structured invoice data.

    Args:
        document: The OCR result from src/ocr/extractor.py.

    Returns:
        ExtractedInvoice with the fields Gemini could confidently extract
        (unclear fields are left as None by the LLM, per the prompt's rules).

    Raises:
        RateLimitError: If the Gemini free-tier quota (15 req/min) is hit.
            Retried automatically with exponential backoff before being raised.
        ProviderTimeoutError: If Gemini is unavailable or times out.
            Retried automatically with exponential backoff before being raised.
        ExtractionFailedError: If Gemini's response cannot be parsed into
            ExtractedInvoice. Not retried (a malformed response is a prompt/
            schema issue, unlikely to be fixed by retrying blindly).
    """
    logger.info("Starting LLM extraction: %s", document.source_file)

    structured_llm = _build_structured_llm()
    prompt = _EXTRACTION_PROMPT_TEMPLATE.format(text=document.text)

    try:
        result = structured_llm.invoke(prompt)
    except ClientError as exc:
        if exc.code == _RATE_LIMIT_HTTP_CODE:
            raise RateLimitError("Gemini rate limit exceeded (free tier: 15 req/min)") from exc
        raise ExtractionFailedError(f"Gemini client error: {exc}") from exc
    except ServerError as exc:
        raise ProviderTimeoutError(f"Gemini server error: {exc}") from exc

    if not isinstance(result, ExtractedInvoice):
        raise ExtractionFailedError(f"Gemini returned an unexpected result type: {type(result)}")

    logger.info("Finished LLM extraction: %s", document.source_file)

    return result
