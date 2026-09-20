from __future__ import annotations

import re

# Data minimisation (GDPR art. 5-1-c): bank / contact details are not needed to extract an
# invoice's amounts, so they never leave the machine. Names stay (they are extracted fields).
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# French phone numbers: 06 12 34 56 78, 0612345678, +33 6 12 34 56 78, 06.12.34.56.78
_PHONE = re.compile(r"(?<![\d.,])(?:\+33|0033|0)[ .]?[1-9](?:[ .-]?\d{2}){4}(?!\d)")

# The prompt wraps the document in these tags; a PDF containing them could "close" the data
# block and write instructions outside of it.
PROMPT_DELIMITER = "invoice_text"
_DELIMITER = re.compile(rf"</?\s*{PROMPT_DELIMITER}\s*>", re.IGNORECASE)


def prepare_text_for_llm(text: str) -> str:
    """Return the document text as it may be sent to the LLM provider.

    Masks IBAN, e-mail addresses and phone numbers, and removes any occurrence of the
    prompt's own delimiter tags.
    """
    text = _DELIMITER.sub("[removed]", text)
    text = _IBAN.sub("[IBAN]", text)
    text = _EMAIL.sub("[EMAIL]", text)
    return _PHONE.sub("[PHONE]", text)
