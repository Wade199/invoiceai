# Prompt Engineering — Module LLM (P2)

> Documente le prompt utilisé par `src/llm/gemini_adapter.py` et sa validation,
> conformément à `PROJECT_BRIEF.md` §5.5.

---

## Approche

Le format JSON n'est **pas** forcé via un `PydanticOutputParser` manuel (parsing de texte +
instructions de formatage dans le prompt), mais via **`llm.with_structured_output(ExtractedInvoice)`**
de LangChain, qui s'appuie sur le structured output natif de Gemini (function calling). Gemini
retourne directement une instance `ExtractedInvoice` validée par Pydantic — plus fiable qu'un
parsing de texte JSON fait à la main.

Le prompt se concentre donc sur les **instructions métier**, pas sur le format de sortie :

```text
You are an expert at extracting structured data from French business invoices
and quotes (factures/devis).

Extract these fields from the invoice text below:
- invoice_number, date (ISO 8601), supplier, client
- lines (description, quantity, unit_price HT, total HT)
- subtotal_ht, tva_rate (décimal), total_ttc

Rules:
- If a value is missing, ambiguous, or you are not confident about it, return
  null for that field. NEVER guess or invent a value.
- Amounts are numbers (dot as decimal separator), not strings.
- Normalize dates to ISO 8601 even if written differently in the source.

[1 exemple few-shot complet]

Now extract the data from this invoice:
{text}
```

## Garde-fous anti-hallucination

1. **Consigne explicite** : "If a value is missing, ambiguous, or you are not confident about
   it, return null. NEVER guess or invent a value." — répond directement au point critique
   §5.4 du `PROJECT_BRIEF.md` (les LLM hallucinent des chiffres)
2. **Schéma Pydantic** : tous les champs métier sont `\| None` (voir `TECHNICAL_DESIGN.md` §2.1) —
   le schéma lui-même autorise/encourage le `null` plutôt que de forcer une valeur
3. **Validation post-extraction** (à venir, §2.3) : `validate_invoice()` vérifiera la cohérence
   mathématique des montants et posera `extraction_confidence: "low"` si incohérent — un
   garde-fou indépendant du prompt, qui rattrape les hallucinations que le prompt n'a pas évitées

## Validation empirique — 5/5 factures fictives

Testé sur les 5 PDF de `data/fake_invoices/` (pipeline complet OCR → LLM) :

| Facture | Numéro | Date | Fournisseur | Lignes | Sous-total HT | Total TTC | Résultat |
|---------|--------|------|-------------|--------|---------------|-----------|----------|
| fake_invoice_01.pdf | INV-234053 | 2026-02-24 | Labbé et Fils | 2/2 | 850.84 ✅ | 1021.01 ✅ | Correct |
| fake_invoice_02.pdf | INV-356778 | 2026-04-18 | Fabre Ledoux SARL | 2/2 | 652.39 ✅ | 782.87 ✅ | Correct |
| fake_invoice_03.pdf | INV-201629 | 2026-01-28 | Peltier S.A. | 2/2 | 726.00 ✅ | 871.20 ✅ | Correct |
| fake_invoice_04.pdf | INV-764544 | 2026-04-06 | Pinto Gillet SARL | 3/3 | 4711.78 ✅ | 5654.14 ✅ | Correct |
| fake_invoice_05.pdf | INV-781177 | 2026-08-07 | Letellier | 3/3 | 1944.02 ✅ | 2332.82 ✅ | Correct |

**100% de précision** (tous les champs, y compris les nombres de lignes de facture) sur ce jeu de
test. À noter : ce sont des factures fictives propres et bien structurées (texte natif, mise en
page simple) — pas représentatif de la variabilité de vraies factures PME. Le prompt sera à
re-tester/ajuster si des faux positifs apparaissent sur des PDF réels en P3/P4.

## Décisions figées

- **Pas de `PydanticOutputParser` manuel** — `with_structured_output()` est plus robuste, moins
  de code, et gère nativement le structured output de Gemini
- **1 seul exemple few-shot** dans le prompt (pas 2 comme suggéré dans `PROJECT_BRIEF.md`) — le
  1er test à 100% de précision n'a pas montré besoin d'un 2e exemple ; à revoir si la précision
  baisse sur des factures réelles plus variées
