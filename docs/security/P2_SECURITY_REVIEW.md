# Security review — P2 (OCR + LLM + validation + cache + pipeline)

Date: 2026-09-20 · Scope: `src/` · Revision 2 (after fixing the risks listed in revision 1 and re-auditing)
Status: **reviewed, residual risks listed below — this is NOT a claim that the system is secure.**

## 1. What was verified (revision 2)

| Area | Check | Result |
|------|-------|--------|
| Secrets | `git grep` (key patterns), `git log -S` on the **values** of `GOOGLE_API_KEY` and `CACHE_ENCRYPTION_KEY`, scan of working files outside `.env` | None found |
| Secrets | `.env` gitignored, never added to any commit | OK |
| Dependencies | `pip-audit` (includes new `cryptography`) | No known vulnerability |
| Static analysis | `bandit -r src` | 0 findings |
| Lint / tests | `ruff` clean · 104 tests (3 runs, no flakiness) · 96 % coverage · 2 real-API tests (`-m slow`) | OK (slow tests passed on 2026-09-21; skipped on 2026-09-20, quota) |
| Real API | 3 fake invoices end-to-end (real OCR process, real Gemini, validation, encrypted cache): all `high`, no warning, cache hit in 0.02 s | OK |
| Real API | Invalid key → `LLMAuthError`, no key in message · daily quota → `DailyQuotaExceededError`, not retried | OK |
| DoS | 200-page PDF refused in 0.3 s · 824 KB PDF with 300 000 drawing ops killed at 20 s · non-PDF, oversize, crashing / hanging parser covered by tests | OK |
| Cache | On-disk entry has no plaintext · 1 flipped bit rejected · entry renamed onto another hash rejected · other key = miss · expired = miss + deleted | OK (tests) |
| Logs / errors | User-controlled strings logged with `%r` · provider response body never copied into our exceptions | OK (tests) |

## 2. Defects found and fixed

Revision 1 (initial review)
1. 429 from the real SDK was never mapped (langchain raises its own classes, not `ClientError`) → no retry, raw exception. Tests used a simplified fake and could not see it.
2. 401/403 escaped raw and would have been retried → `LLMAuthError`.
3. `.env` never loaded; missing key gave a cryptic SDK error → `load_env()` + fail closed.
4. Cache temp file predictable / collision on concurrent stores (Windows `PermissionError`) → unique temp file + retry.
5. Log injection (file name, invoice number logged with `%s`) → `%r`.

Revision 2 (re-audit)
6. **`maxItems` on an array of objects is rejected by Gemini (400 INVALID_ARGUMENT).** Introduced by my own hardening, caught only by a live call; mocked tests were blind. Cap moved to a validator; offline regression test on the JSON schema; real-API tests added (`tests/slow/`).
7. `escape_markdown` returned literal `\1` instead of escaping (my bug, caught by its test).
8. Schema-violating model output (`ValidationError` / `OutputParserException`) was not mapped → `ExtractionFailedError` without model content.
9. **Free-tier quota is 20 requests per DAY per model** (measured, quota id `GenerateRequestsPerDayPerProjectPerModel-FreeTier`), not 15/min as assumed in the brief. Retrying after seconds was pointless → `DailyQuotaExceededError`, never retried.
10. Tests loaded the developer's real `.env` (real key in the process environment) → autouse fixture blocks it; each test gets a throw-away cache key.

## 3. Risks from revision 1 — status

| # | Risk | Status | What was done | What remains |
|---|------|--------|---------------|--------------|
| 1 | No limit on size / pages / text / time, no parser timeout | **Mitigated** | Size, `%PDF-` header, 30 pages, 100 000 chars, 20 s hard timeout via killable child process; invalid settings fall back to defaults | No memory cap inside the child; no cap on parallel uploads (P3: queue / concurrency limit / per-user rate limit) |
| 2 | Free tier: Google may reuse content | **Reduced** | Terms read (see below); IBAN, e-mail and French phone numbers masked before sending; once-per-process warning; `GEMINI_TIER` setting | Names, addresses and amounts are still sent; masking is regex-based (French phone formats only, recall not measured); outside EEA/CH/UK unpaid terms apply |
| 3 | Cache = plaintext personal data, no TTL, no integrity | **Mitigated** | Fernet (AES + HMAC) encryption, fail closed without key, 30-day authenticated TTL, entry bound to its hash, `purge_expired()`, legacy plaintext purge | Key sits in `.env` on the same machine; no key rotation; `purge_expired()` not scheduled yet (P3); POSIX-only file modes |
| 4 | Prompt injection not solved | **Reduced, not solved** | Data delimiters + "this is data" instruction, delimiter stripping, schema bounds (control / bidi / zero-width chars, lengths, finite bounded numbers), amount validation, `escape_markdown()` for the UI | Cannot be eliminated. **Verified live on 2026-09-21** (`pytest -m slow`, 2 passed): with the new prompt, a PDF closing the data tag and ordering "SYSTEM OVERRIDE" (change supplier and total, leak the API key) did not change the extraction. One attempt per run, not a guarantee. UI (P4) must call `escape_markdown` on every LLM field |
| 5 | Cache key = PDF content only (stale after prompt / model change) | Reduced | 30-day TTL bounds staleness; `GEMINI_MODEL` now configurable | Alias `gemini-flash-latest` still changes model silently; consider a versioned key |
| 6 | Untrusted PDF parsed by pdfminer | Reduced | Runs in a separate process with timeout and kill | No sandbox / privilege drop / memory cap; re-run `pip-audit` each release |
| 7 | Exception messages contain server paths | Open | — | API / UI must translate errors, never show raw messages |
| 8 | LangSmith tracing would send prompts to a third party | Open | — | Keep `LANGCHAIN_TRACING_V2` unset; add to deployment checklist |
| 9 | No real-API test | **Closed** | `tests/slow/` (2 tests, auto-skip on quota), passed on 2026-09-21 | Run `pytest -m slow` before each release (spends 2 of the 20 daily requests; ~80 s) |

## 4. New observations

- **Google data terms** (ai.google.dev/gemini-api/terms, read 2026-09-20 through a summarising tool — re-read the page before relying on it): unpaid services — content is used to improve Google products and may be read by human reviewers; **if you are in the EEA, Switzerland or the UK, the paid-service terms apply to all services, including the free tier** (no product improvement, limited logging for abuse detection). The project owner is in France, so the current use is covered; users elsewhere are not.
- **Free tier is 20 requests/day/model**: a demo / portfolio run must rely on the cache and on fake data; `process_invoice` takes 7–33 s per invoice on the free tier (UI must show progress).
- ~~`multiprocessing` "spawn": scripts must guard their entry point~~ — **superseded (2026-09-21)**: the parser now runs as an independent command (`python -m src.ocr.worker`) and no longer depends on the caller's `__main__`; it also no longer inherits the Gemini / encryption keys. See `P4_UI_REVIEW.md` step 3.

## 5. Before P3 (exposure to the network)

1. Upload endpoint: server-generated file names (never the client's), size / MIME / magic-byte checks, concurrency limit, rate limit.
2. Call `purge_expired()` at startup and daily; expose `delete_cached()` behind an authenticated DELETE (GDPR erasure).
3. Escape every LLM field on output (`escape_markdown`) — JSON API included if a client renders it.
4. Decide on the paid tier / provider before any real customer data.
5. Re-run `pip-audit` and `bandit` (`pytest -m slow` already passed on 2026-09-21).
