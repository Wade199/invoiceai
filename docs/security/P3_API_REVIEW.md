# Security review — P3 / step 3 (REST API)

Date: 2026-09-21 · Scope: `src/api/app.py`, `routes.py`, `schemas.py`, `middleware.py`, `security.py`, `upload.py`, and their wiring to the database, the cache, the pipeline and the export
Model: V1 = one local user, API on `127.0.0.1`, bearer token (`TECHNICAL_DESIGN.md` §4.1).
Status: **reviewed, residual risks listed — NOT a claim that the API is secure.** Do not expose it to the Internet as is (no accounts, no TLS).

## 1. What was verified

| Area | Check | Result |
|------|-------|--------|
| Authentication | Every route refuses a missing or wrong token; a test walks the real route table so a route added later without protection fails; `/health` is the only open route and returns no data | OK (HTTP tests + real server) |
| Startup | The app refuses to start without a valid `API_TOKEN` (missing, empty, < 32 chars) or a valid encryption key | OK (test) |
| Host / DNS rebinding | `Host: evil.example` → 400 (also on a real server) | OK; not tried in a real browser |
| Surface | `/docs`, `/redoc`, `/openapi.json` are 404 unless `API_DOCS=1`; no CORS header ever sent, pre-flight included | OK |
| Headers | `Cache-Control: no-store`, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, CSP `default-src 'none'` on **every** kind of response: 200, 401, 404, 413, 422, 400 (bad host), 500 | OK (tests) |
| Validation | Bounded `limit` / `offset` / `q` / `ids` (≤ 200) / `columns`; ids must be canonical UUIDs; 422 answers never echo the value received | OK (tests + real server) |
| Mass assignment | `PUT` rejects `extraction_confidence`, `warnings`, `id`, `pdf_hash`, `expires_at`, `status`; the server recomputes reliability, so a client cannot mark its own edit "high" | OK (tests) |
| Output | Response models are explicit; the PDF hash never appears in any response | OK (tests + real server) |
| Errors | 9 pipeline / storage failures map to fixed French messages, no path or exception text; an unexpected `RuntimeError("secret C:\\...")` gives a plain 500; the PDF is deleted even then | OK (tests) |
| Logs | Only exception **types** and status codes are logged; with `--no-access-log` a search term (`?q=...`) is not written anywhere; no secret in the server log | OK (real server) |
| Upload flow | Real server: 300 MB chunked stream, with and without token, is cut after ~1.8 MB, nothing written to the server temp dir or the upload dir; uploaded PDF removed after processing | OK |
| Concurrency | Real server, 4 simultaneous uploads with a limit of 2: 2 × 201, 2 × 503 with `Retry-After`, upload folder empty afterwards | OK |
| Data at rest | After an upload: neither the `.db` file nor the cache contains the supplier or invoice number in clear text; after `DELETE` the cache file is gone and the ciphertext is physically absent from the `.db` file | OK (real server) |
| Retention | Expired records invisible on every route; startup purge removes expired rows, their cache entries and orphan uploads | OK (test) |
| Export | Hostile supplier / client / number / description (`=cmd|…`, `@SUM`, `-2+3`) come out prefixed with `'` through the API, in both files; the file name is built from dates only | OK (test) |
| Static / deps | `ruff`, `bandit` 0 findings, `pip-audit` no known vulnerability, 387 tests (3 runs), 98 % coverage | OK |

## 2. Defects found and fixed in this step

1. **A failure to write the cache lost a Gemini answer that was already paid for** (found on a real server: the probe's folder path exceeded Windows' 260-character limit, the cache write failed, and the request returned 500 after Gemini had answered). The cache is an optimisation: a write failure is now logged and ignored. A missing / invalid key still fails **before** the Gemini call (both behaviours tested).
2. **Domain errors were not logged at all**, which made that failure hard to diagnose. The handler now logs the exception type and the HTTP status (never the message).
3. `README.md` linked to a file deleted during the repository clean-up; it now documents the keys, `make api` and the local-only security model.

## 3. Residual risks

| # | Risk | Severity | Note |
|---|------|----------|------|
| 1 | **Never tested in a real browser**: DNS-rebinding (`Host`) and CORS behaviour are verified with HTTP clients only | Low | Try once from a browser console against a foreign origin |
| 2 | **`--no-access-log` is a launch flag**, not enforced by the app: started any other way, uvicorn logs `?q=Orange` (personal data) | Medium | `make api` sets it; README says to use it. Moving the search to `POST` would remove the issue |
| 3 | Rate limit only on `POST /invoices`; a valid token holder can call list / export in a loop (each call decrypts up to 500 rows) | Low | Single local user |
| 4 | Token in `.env`, sent in clear over HTTP on localhost; no TLS, no accounts | Medium if exposed | README: local only |
| 5 | Purge runs at startup only (retention is also enforced on read); a process running for weeks accumulates expired files until restart | Low | Add a periodic task if the API is left running |
| 6 | A very deep project path can exceed Windows' 260-character limit: uploads fail with 500 (cache failures are now tolerated) | Low | Keep the project near the drive root |
| 7 | Two uploads of the same PDF create two records (extraction comes from the cache) | Low | Documented; user deletes |
| 8 | Real Gemini through the API was **not** exercised in this review (daily quota exhausted, ~09:00 Paris reset); the extraction was faked at the LLM boundary only, everything else was real | Medium | Task 19: rerun `pytest -m slow` and one real `POST /invoices` |
| 9 | Exported CSV leaves the retention / encryption perimeter | Medium | UI must warn next to the download button (P4) |
| 10 | Open Excel with a hostile export not done | Low | Task 20 |
| 11 | No slow-body (slow-loris) timeout, uvicorn defaults | Low (local) | A reverse proxy would handle it |

## 4. Before P4 (UI)
1. The UI must call `escape_markdown` on every field coming from the API (supplier, client, lines, warnings, file name).
2. The UI holds the token (`API_TOKEN`) server-side (Streamlit runs on the server): never send it to the browser.
3. Warn about the CSV download (residual risk 9) and about the free-tier Gemini data policy on the upload screen.
