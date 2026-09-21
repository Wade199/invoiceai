# Security review — P3 / step 2 (CSV export)

Date: 2026-09-21 · Scope: `src/services/export.py`
Status: **reviewed, residual risks listed — NOT a claim that opening the files is safe in every application.** No route exposes the export yet (step 3).

## 1. What was verified

| Area | Check | Result |
|------|-------|--------|
| Formula injection | 11 hostile payloads (`=1+1`, `+`, `-`, `@`, `=cmd\|' /C calc'!A0`, `-2+3+cmd\|...`, tab, CR, leading blanks, leading newline, `=HYPERLINK(...)`) planted in **every** attacker-controlled text field (invoice number, date, supplier, client, warnings, file name, line description) of **both** files: none leaves the export starting like a formula | OK (test) |
| Numbers | Amounts are formatted by our code, so a credit note's `-100,00` stays numeric and is not prefixed | OK (test) |
| Ordinary text | `Orange`, `A-1`, `N°-1`, `x=1`, `a+b`, `é=mc2` are left untouched (no false positives on the common cases) | OK (test) |
| Structure | A field containing `;`, `,`, `"`, CR/LF cannot add or shift columns / rows (parsed back with `csv`) | OK (test) |
| Columns | Requested columns come from an allowlist; unknown names (`__class__`) refused | OK (test) |
| File name | `suggested_filename` is built from dates only, never from user text (`../../evil.pdf` as a file name has no effect) | OK (test) |
| Excel / accents | UTF-8 with BOM; French locale uses `;` and a decimal comma (Excel FR), international locale `,` and a decimal point | OK (test) |
| Volume | 500 invoices × 200 lines (100 000 rows) exported in well under 5 s | OK (test) |
| Static / deps | `ruff`, `bandit` 0 findings, `pip-audit` no known vulnerability, 314 tests, 97 % coverage | OK |

## 2. Residual risks

| # | Risk | Severity | Note |
|---|------|----------|------|
| 1 | **Not opened in a real spreadsheet.** The defence (leading apostrophe) is the OWASP recommendation, verified by tests on the produced text, not in Excel / LibreOffice / Google Sheets | Low | Try a hostile export in Excel once before publishing |
| 2 | The apostrophe is visible in the cell (`'=1+1`): a legitimate supplier whose name starts with `-` or `=` sees it added | Low | Accepted: safe by default beats pretty |
| 3 | Some exotic triggers are not covered (e.g. `%` or `\|` in old DDE syntaxes): OWASP's list is `= + - @ TAB CR` | Low | Same list as OWASP; extend if a real case appears |
| 4 | Export happens in memory (whole file built before sending) | Low | Bounded: `list` is capped at 500 invoices, each at 200 lines |
| 5 | A downloaded CSV is personal data outside the app: it escapes the retention and encryption rules | Medium | UI must say so next to the download button (P4) |
| 6 | Excel `.xlsx` export not implemented (wireframe offers it) | — | Deferred; CSV covers V1 |

## 3. For step 3 (routes)
1. Export routes read through `InvoiceRepository` (retention enforced) and send `Content-Disposition` with `suggested_filename` only, plus `X-Content-Type-Options: nosniff` and `Content-Type: text/csv; charset=utf-8`.
2. Bound the selection (`ids` count) so a request cannot ask for an unbounded export.
3. Protect with the bearer token like every other route.
