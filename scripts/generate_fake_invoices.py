"""Generate fake PDF invoices as test fixtures for the OCR/LLM pipeline (P1/P2).

Usage:
    python scripts/generate_fake_invoices.py [--count 5] [--out data/fake_invoices]
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from faker import Faker
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

TVA_RATE = 0.20


def build_invoice_data(fake: Faker) -> dict:
    line_count = random.randint(2, 5)
    lines = []
    for _ in range(line_count):
        qty = random.randint(1, 10)
        unit_price = round(random.uniform(10, 500), 2)
        lines.append(
            {
                "description": fake.bs().capitalize(),
                "qty": qty,
                "unit_price": unit_price,
                "total": round(qty * unit_price, 2),
            }
        )

    subtotal_ht = round(sum(line["total"] for line in lines), 2)
    total_tva = round(subtotal_ht * TVA_RATE, 2)
    total_ttc = round(subtotal_ht + total_tva, 2)

    return {
        "invoice_number": f"INV-{fake.unique.random_number(digits=6)}",
        "date": fake.date_this_year().isoformat(),
        "supplier": fake.company(),
        "supplier_address": fake.address().replace("\n", ", "),
        "client": fake.company(),
        "lines": lines,
        "subtotal_ht": subtotal_ht,
        "tva_rate": TVA_RATE,
        "total_tva": total_tva,
        "total_ttc": total_ttc,
    }


def render_invoice_pdf(data: dict, path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 30 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, f"FACTURE {data['invoice_number']}")
    y -= 10 * mm

    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, f"Date: {data['date']}")
    y -= 6 * mm
    c.drawString(20 * mm, y, f"Fournisseur: {data['supplier']}")
    y -= 6 * mm
    c.drawString(20 * mm, y, f"Adresse: {data['supplier_address']}")
    y -= 6 * mm
    c.drawString(20 * mm, y, f"Client: {data['client']}")
    y -= 12 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Description")
    c.drawString(110 * mm, y, "Qte")
    c.drawString(130 * mm, y, "PU HT")
    c.drawString(160 * mm, y, "Total HT")
    y -= 6 * mm
    c.setFont("Helvetica", 10)

    for line in data["lines"]:
        c.drawString(20 * mm, y, line["description"][:45])
        c.drawString(110 * mm, y, str(line["qty"]))
        c.drawString(130 * mm, y, f"{line['unit_price']:.2f}")
        c.drawString(160 * mm, y, f"{line['total']:.2f}")
        y -= 6 * mm

    y -= 6 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(130 * mm, y, "Sous-total HT:")
    c.drawString(160 * mm, y, f"{data['subtotal_ht']:.2f}")
    y -= 6 * mm
    c.drawString(130 * mm, y, f"TVA ({data['tva_rate'] * 100:.0f}%):")
    c.drawString(160 * mm, y, f"{data['total_tva']:.2f}")
    y -= 6 * mm
    c.drawString(130 * mm, y, "Total TTC:")
    c.drawString(160 * mm, y, f"{data['total_ttc']:.2f}")

    c.showPage()
    c.save()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("data/fake_invoices"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    fake = Faker("fr_FR")
    Faker.seed(args.seed)

    args.out.mkdir(parents=True, exist_ok=True)

    for i in range(1, args.count + 1):
        data = build_invoice_data(fake)
        pdf_path = args.out / f"fake_invoice_{i:02d}.pdf"
        render_invoice_pdf(data, pdf_path)
        print(f"Generated {pdf_path} (total_ttc={data['total_ttc']:.2f} EUR)")


if __name__ == "__main__":
    main()
