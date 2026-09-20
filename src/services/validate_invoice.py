from __future__ import annotations

import logging

from src.models.schemas import ExtractedInvoice

logger = logging.getLogger(__name__)

# Absolute tolerance in euros: covers per-line rounding to the cent.
AMOUNT_TOLERANCE = 0.02


def _close(a: float, b: float) -> bool:
    # Round the gap to the cent: float noise (0.0200000000000031) must not
    # push a legitimate 2-cent rounding difference over the tolerance.
    return round(abs(a - b), 2) <= AMOUNT_TOLERANCE


def validate_invoice(invoice: ExtractedInvoice) -> ExtractedInvoice:
    """Check arithmetic consistency of an extracted invoice.

    LLMs can hallucinate amounts, so we re-compute what can be re-computed:
      1. each line: quantity * unit_price ≈ total
      2. sum(lines.total) ≈ subtotal_ht
      3. subtotal_ht * (1 + tva_rate) ≈ total_ttc

    A rule is skipped when one of its inputs is missing (null is a legitimate
    LLM answer, not an inconsistency). Never raises: on failure the returned
    copy has `extraction_confidence="low"` and one warning per broken rule.
    The input object is not mutated.

    Args:
        invoice: Invoice as returned by the LLM adapter.

    Returns:
        A copy of the invoice with confidence and warnings updated.
    """
    new_warnings: list[str] = []

    for index, line in enumerate(invoice.lines, start=1):
        expected = line.quantity * line.unit_price
        if not _close(expected, line.total):
            new_warnings.append(
                f"Line {index}: quantity * unit_price = {expected:.2f} but total = {line.total:.2f}"
            )

    if invoice.lines and invoice.subtotal_ht is not None:
        lines_sum = sum(line.total for line in invoice.lines)
        if not _close(lines_sum, invoice.subtotal_ht):
            new_warnings.append(
                f"Sum of lines = {lines_sum:.2f} but subtotal_ht = {invoice.subtotal_ht:.2f}"
            )

    if (
        invoice.subtotal_ht is not None
        and invoice.tva_rate is not None
        and invoice.total_ttc is not None
    ):
        expected_ttc = invoice.subtotal_ht * (1 + invoice.tva_rate)
        if not _close(expected_ttc, invoice.total_ttc):
            new_warnings.append(
                f"subtotal_ht * (1 + tva_rate) = {expected_ttc:.2f} "
                f"but total_ttc = {invoice.total_ttc:.2f}"
            )

    if not new_warnings:
        return invoice.model_copy(deep=True)

    logger.warning("Invoice %r failed validation: %s", invoice.invoice_number, new_warnings)
    return invoice.model_copy(
        update={
            "extraction_confidence": "low",
            "warnings": [*invoice.warnings, *new_warnings],
        },
        deep=True,
    )
