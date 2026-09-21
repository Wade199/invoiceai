# Security review — P3 / 13a (upload and API security layer)

Date: 2026-09-21 · Scope: `src/api/middleware.py`, `upload.py`, `security.py`, `scripts/generate_api_token.py`
Model: V1 = one local user, API on `127.0.0.1`, protected by a bearer token (see `TECHNICAL_DESIGN.md` §4.1).
Status: **reviewed, residual risks listed — NOT a claim that the API is secure.** The routes that wire these pieces together (13b) are not written yet and need their own review.

## 1. What was verified

| Area | Check | Result |
|------|-------|--------|
| Size | Body over the limit refused by a declared `Content-Length` (never reaches the app) and cut while streaming when the header is absent, missing or lying | OK (unit + HTTP tests) |
| Size | **Real uvicorn server**: 300 MB chunked stream cut after ~1.8 MB received (limit 1 MB), nothing written to the server temp dir or to `UPLOAD_DIR` | OK |
| File name | Client name never used as a path: `../../x.pdf`, `C:\...`, NUL / CR / LF, RTL override → stored as `uuid4().hex + ".pdf"` inside `UPLOAD_DIR`, display label sanitised | OK |
| Type | MIME must be `application/pdf` AND bytes must start with `%PDF-` at offset 0; empty file refused; exe with a `.pdf` name refused; nothing left on disk after any refusal | OK |
| Token | Constant-time comparison; missing / wrong / short / wrong scheme / trailing space refused; **no server token or token < 32 chars → everything refused (500), never open**; token never echoed | OK |
| Limits | Rate limit (sliding window, capped key table that fails closed) and concurrency limit (released on error), `Retry-After` returned | OK |
| Errors | Every concrete exception has a fixed French message; server paths and exception text never sent; a guard test fails when a new exception is added without a mapping | OK |
| Cleanup | Upload deleted in `finally` even on error; `delete_upload` refuses files outside `UPLOAD_DIR`; `purge_stale_uploads()` removes orphans | OK |
| Static / deps | `ruff`, `bandit` 0 findings, `pip-audit` no known vulnerability, 209 tests, 97 % coverage | OK |

## 2. Defects found and fixed during the work

1. **FastAPI turns any exception raised while reading the body into a generic 400**, so the first middleware design (raise an internal exception) answered 400 instead of 413. Redesigned: fake `http.disconnect` to make the app stop reading, drop its answer, send our own 413.
2. A test claimed the server stopped reading, but the test client reads its whole stream first (it measured the client, not the server). Replaced by a direct middleware test with a fake stream + the real-server measurement above.
3. `make api` pointed to an application that does not exist before 13b: removed (TODO left in the Makefile).

## 3. Residual risks

| # | Risk | Severity | Note |
|---|------|----------|------|
| 1 | **Token checked after the body is read** (FastAPI parses the body before dependencies): an unauthenticated caller can make the server read up to the limit (10 MB by default, spooled to the OS temp dir above 1 MB) before the 401 | Low (local, bounded) | Could be closed by checking the token in the middleware; not done in V1 |
| 2 | **Wiring not done**: nothing yet applies the middleware, the token, the limiters or the cleanup to real routes | Must-do in 13b | Re-review 13b; the integration test app shows the intended wiring |
| 3 | No timeout on a slow request body (slow-loris): a client can hold a connection open while trickling bytes | Low (local) | A reverse proxy would handle it if the API is ever exposed |
| 4 | Upload sits **unencrypted on disk** while being processed (seconds to ~1 min), plus Starlette temp files above 1 MB; a crash leaves them until the next `purge_stale_uploads()` (1 h) | Medium | Deleted in `finally`; call the purge at startup (13b); disk encryption of the machine is the real protection |
| 5 | **Token in `.env` in clear text, sent over plain HTTP** on localhost: fine on `127.0.0.1`, not if the API is ever reachable from another machine | Medium if exposed | README must say: never expose as is; TLS + accounts (option B) first |
| 6 | A malicious file that does start with `%PDF-` passes this layer | Medium | Handled downstream: PDF parsed in a killable child process with limits (P2) |
| 7 | Rate limiter is in memory and per process: resets on restart, useless with several workers; key = socket address (all clients look the same behind a proxy; `X-Forwarded-For` deliberately ignored) | Low (local) | Fine for V1 |
| 8 | CORS not configured and the token travels in an `Authorization` header: a web page open in the browser should not be able to call the API (custom header needs a pre-flight that is refused) | Low | Reasoned from the design, **not tested in a real browser** |
| 9 | POSIX file modes (0o600 / 0o700) do nothing on Windows | Low | User-profile ACL applies |
| 10 | Gemini daily-quota guard before the call not implemented (the 429 is translated, not prevented) | Low | 13b |

## 4. Before merging 13b

1. Wire middleware, `require_token` on every route (including DELETE), `rate_limiter.check`, `ConcurrencyLimiter.slot`, `save_upload` → `process_invoice` → `delete_upload` in `finally`.
2. Register an `InvoiceAIError` handler using `to_http_error`; disable the auto-generated docs unless explicitly enabled.
3. `purge_expired()` and `purge_stale_uploads()` at startup; `make api` on `127.0.0.1`.
4. Re-run this review's checks on the real app, plus a real-server probe.
