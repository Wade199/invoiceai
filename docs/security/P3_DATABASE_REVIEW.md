# Security review — P3 / step 1 (data model and repository, task 14)

Date: 2026-09-21 · Scope: `src/core/database.py`, `src/core/crypto.py`, `src/models/invoice_record.py`, `src/services/repository.py` (+ the cache now sharing `crypto.py`)
Status: **reviewed, residual risks listed — NOT a claim that the storage is secure.** No route uses the repository yet (steps 2-3).

## 1. What was verified

| Area | Check | Result |
|------|-------|--------|
| Confidentiality | Raw bytes of the `.db` file searched for supplier, client, invoice number, file name, amounts, line descriptions: none present | OK (test) |
| Confidentiality | Plain columns hold only id, dates, status, PDF hash, schema version | OK (design + test) |
| Erasure | `PRAGMA secure_delete = ON` on every connection: after `DELETE` the ciphertext is **physically gone** from the file (checked by reading the file) | OK (test) |
| Erasure | `delete` removes the cache entry first, then the row; if the cache cannot be erased nothing else is touched and the caller can retry | OK (test) |
| Erasure | `purge_expired` removes expired rows + their cache entries, also rows that can no longer be decrypted (works from plain columns) | OK (test) |
| Retention | Expired rows are treated as absent on read, before any purge; `update` never extends `expires_at` | OK (test) |
| Integrity | One flipped bit in a payload: `get` raises `StorageError`, `list` skips the row and keeps working | OK (test) |
| Integrity | A payload copied onto another row is refused (the row id is inside the encrypted payload) | OK (test) |
| Key | Missing or invalid key: `StorageError`, nothing written in clear (fail closed); other key: rows unreadable, list does not crash | OK (test) |
| Injection | Malformed ids (`'; DROP TABLE`, `../../x`, upper-case UUID) are just "not found"; SQL-looking content is stored as data; queries are parameterised by SQLAlchemy | OK (test) |
| Path safety | A tampered `pdf_hash` column (`../victim`) is never turned into a path; the record can still be erased | OK (test) |
| Concurrency | 40 records created and read from 8 threads: no lock error, no corruption | OK (test) |
| Static / deps | `ruff`, `bandit` 0 findings, `pip-audit` no known vulnerability, 268 tests (3 runs), 97 % coverage | OK |

## 2. Defects found and fixed during the work

1. **Tests were writing into the real `data/` folder** (`data/cache/*.enc`, and a `data/invoiceai.db` after a `monkeypatch.undo()` that dropped every fixture). Only test data, encrypted with a throw-away key, and gitignored, but wrong. Removed, the cache folder is now isolated for every test (`conftest.py`), the faulty test fixed, and `data/` verified untouched after the full suite.
2. A tampered `pdf_hash` would have raised `ValueError` inside `purge_expired` and blocked the purge. Now logged and ignored; the row is still erased.

## 3. Residual risks

| # | Risk | Severity | Note |
|---|------|----------|------|
| 1 | **One key protects cache AND database** (`CACHE_ENCRYPTION_KEY`). Losing it = losing the whole history (rows become unreadable until they expire). No key rotation (`MultiFernet`) | Medium (availability) | Back the key up (done for the cache key); name is historical, kept to avoid breaking existing `.env` files |
| 2 | Plain columns leak metadata: when invoices were processed, their reliability flag, and the PDF's SHA-256 (someone holding a known PDF can confirm it was processed) | Low | Accepted: needed for retention, filtering and cache erasure |
| 3 | Search / filters decrypt every non-expired row on each call (only the output is capped at 500) | Low | Fine for hundreds of invoices; revisit if the volume grows |
| 4 | No migrations (Alembic): a schema change after real use needs a manual step | Low | `schema_version` is stored; add Alembic when the schema first changes |
| 5 | `secure_delete` does not scrub the SQLite journal / OS-level copies (SSD wear levelling, backups, shadow copies) | Low | The journal only ever holds ciphertext; disk encryption of the machine is the real protection |
| 6 | POSIX file modes (0o600 / 0o700) do nothing on Windows | Low | User-profile ACL applies |
| 7 | Single-user model: no `user_id` column, every record belongs to "the" user | By design | Option B adds `users` + `user_id` |
| 8 | Rows are only as trustworthy as the key: whoever has the key and the file can forge records (Fernet authenticates, it does not identify the writer) | Low | Same trust boundary as the cache |

## 4. For steps 2 and 3
1. Routes must go through `InvoiceRepository` inside `session_scope()` and translate `StorageError` with `to_http_error`.
2. Call `InvoiceRepository.purge_expired()` at startup (with `purge_expired()` of the cache and `purge_stale_uploads()`).
3. `DELETE /invoices/{id}` must call `repository.delete` (row + cache), never a bare SQL delete.
4. CSV export: neutralise cells starting with `=`, `+`, `-`, `@` (formula injection).
