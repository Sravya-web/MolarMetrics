# MolarMetrics: developer notes

Technical details that don't belong in the clinic-facing app. User documentation is the
[README](../README.md).

## 1. Architecture

```
web/ (React 19, TypeScript 7, Vite 8, Tailwind 4, Lucide, Recharts)
  │  same-origin /api (Vite proxy in development; FastAPI serves web/dist in production)
  ▼
molarmetrics/api/  (FastAPI + Pydantic)
  app.py           routes, middleware, cookie sessions, static files
  store.py         registry SQLite: sessions, datasets, upload batches
  retention.py     expiry sweeps and verified deletion
  uploads.py       staging, parse cache, validate, atomic import
  overview.py      Overview payload composed from the existing analyses
  ask_service.py   per-dataset agents, answer selection, monthly enforcement
  presenters.py    AnalysisResult -> AnalysisPayload, prohibited-term filter
  schemas.py       API contracts (mirrored by web/src/api/types.ts)
  ▼
molarmetrics/ingest/      CSV import (pure Python, no web code)
molarmetrics/analytics/   metrics.py (SQL), analyses.py, results.py, export.py, params.py
molarmetrics/agent/       LangChain create_agent + ChatOllama (llama3.2:3b), 4 typed tools
molarmetrics/dataset.py   DatasetContext: coverage, capabilities, procedure names, import notes
```

The original Streamlit app (`app.py`, `molarmetrics/ui/`) still runs on the same analytics and the
bundled sample database; all 183 of its original tests pass unchanged.

## 2. Dataset context and capability gating

Every analysis takes `ctx: DatasetContext | None` (`molarmetrics/dataset.py`). Without a context the
sample behaviour is reproduced exactly (`SAMPLE_CONTEXT`); the sample system prompts are
byte-identical to the originals.

* **Coverage** (first/last appointment or payment date) replaces the hard-coded sample period in
  coverage warnings, argument defaults (`params.arg_models_for(ctx)` builds per-dataset Pydantic
  subclasses) and the system prompt.
* **Capabilities**: `appointments`, `dentist_breakdown`, `treatments`, `payments` (and derived
  `outstanding` = treatments + payments). Missing ones make an analysis return
  `status="unavailable"` with a sentence naming the records to add. KPIs omit money items instead
  of reporting zero.
* **Procedure names** come from the dataset; `resolve_procedure_name` matches exact, documented
  alias, loose (punctuation/plural-insensitive), then a *unique* partial match, and rejects ambiguity.
* **Import notes** (review decisions) are appended to the notes of every money result.
* `run_analysis`/`build_tools` refuse an uploaded context without an explicit database path, so an
  upload can never fall back to `data/molarmetrics.db`.

Uploaded databases use the **same table and column names** as the sample (money in INTEGER paise with
CHECK constraints), so `metrics.py` SQL runs unchanged. Differences handled in SQL:
`dentists.display_name` (vs `fictional_display_name`, chosen from a fixed whitelist), grouping by
`appointments.dentist_id` when no dentists table rows exist, and a "No dentist recorded" row so
per-dentist rows always sum to the totals.

## 3. Import pipeline (`molarmetrics/ingest/`)

1. `parsing.parse_csv` rejects workbooks and binary files, decodes UTF-8 (BOM) then cp1252, sniffs the
   delimiter from the header line, renames duplicate headers (warning), flags rows with extra values
   (blocking) and keeps spreadsheet row numbers (header = row 1, blank lines counted).
2. Suggestions: record type (filename hints + header matches), column mapping (exact synonyms,
   then without unit/format words such as "(Rs)", then multi-word containment), status labels.
3. `validate.validate_batch(files, ImportConfig)` → `(ValidationReport, all issues, NormalizedData | None)`.
   Pure and deterministic; called on every review change **and again on import** (the browser's
   state is never trusted). Severities: `blocking`, `review`, `warning`, `info`.
   * Dates: every value is tried against an explicit format list; if both DD/MM and MM/DD read every
     value, the field is *ambiguous* and blocks until the user chooses.
   * Money: `Decimal`, Indian or Western grouping only, ≤ 2 decimal places for rupees, whole numbers
     for paise; blank is missing (never 0). Unit must be confirmed per file.
   * Review groups: payments dated before their treatment's appointment, and treatments on
     cancelled/no-show appointments. Each needs `include` or `exclude`; excluding treatments also
     excludes their payments (the cascade count is shown). Overpayment is checked on what will
     actually be imported.
4. `build.atomic_import`: write all tables in one transaction inside `datasets/.<id>.tmp/`, re-open
   read-only and verify integrity, foreign keys, row counts and exact money totals, then `os.replace`
   into `datasets/<id>/`. The registry insert + activation is one registry transaction; if it fails
   the new folder is removed. Any failure leaves the active dataset unchanged.

## 4. Questions (`molarmetrics/api/ask_service.py` + `molarmetrics/agent/`)

* One `MolarMetricsAgent` per dataset (LRU of 8), bound to that dataset's database path and context.
  The agent is the original LangChain `create_agent` graph with `ChatOllama` (temperature 0, seed 42,
  `num_ctx` 8192), model/tool call limits, one retry for transient server errors, and the
  rule-based clinical-scope check.
* The model reads only `AnalysisResult.to_model_content()`: Python-written facts, metrics with units
  and aggregation, at most 24 rows. The full result goes to the browser.
* Answer selection (`compose`): results with `status="error"` are dropped; the generated text is used
  only if `check_grounding` finds every number in the results, `presenters.prohibited_terms` finds
  nothing (AI, model, tool, SQL, JSON, snake_case identifiers…), and, for monthly questions, it names a
  month. Otherwise the answer is assembled from the most relevant facts. Unavailable results produce
  the "Add … records" sentence; clinical questions get the fixed refusal plus a suggestion if the
  model's reply contains numbers or technical terms.
* Monthly questions: if no monthly result was produced, the monthly analysis (finances or
  appointments) is run deterministically for the same period and shown first. Finance results now
  carry "highest/lowest monthly" facts.
* Conversation memory: last 2 question/answer pairs per (session, dataset), in memory only, cleared
  on dataset switch, sample activation, import and removal.
* Concurrency: one question at a time per session (`409 busy`). Availability is checked (cached 15 s)
  before each question; failures map to plain messages (`503` unavailable, `504` timeout, `502`
  failed) with no stack traces.

## 5. Sessions, ownership and request protection

* Cookie `mm_session`: `secrets.token_urlsafe(32)`, HttpOnly, SameSite=Strict, sliding expiry. The
  registry stores only its SHA-256 (the session ID).
* Every dataset/upload lookup checks `session_id`; foreign or unknown IDs → `404`.
* `TrustedHostMiddleware` (`MOLARMETRICS_ALLOWED_HOSTS`), required `X-MolarMetrics: 1` header on
  non-GET `/api` requests, `Content-Length` cap on uploads, `Cache-Control: no-store` on API responses,
  `nosniff`/`no-referrer`/`DENY` framing headers, and a CSP on the served app.
* No CORS is configured: the browser always uses the same origin.

## 6. Retention (`molarmetrics/api/retention.py`)

One clock: `last_used_at` (datasets) / `last_used_at` (upload batches) / `last_seen` (sessions), each
refreshed on use. `sweep(startup=True)` runs in the lifespan hook and deletes only items older than
the window, plus never-imported `.tmp` folders. A background task repeats the sweep every
`MOLARMETRICS_CLEANUP_INTERVAL_MINUTES`. `AppState.owned()` checks expiry on access (`410`). Folder
deletion refuses paths outside `runtime/datasets` or `runtime/staging` and verifies the folder is gone.
The sample entry has no files to delete.

## 7. Logging policy

* `molarmetrics.api`: `request=<id> <METHOD> <route template> status=<code> ms=<n>`.
* `molarmetrics.ask`: `question request=<id> outcome=<answered|not_available|…|failed> seconds=<n>`.
* `molarmetrics.agent`: error category and exception **type name** only.
* `molarmetrics.retention`: dataset IDs and counts.
* Never logged: question text, cell values, file contents, dataset names. Uvicorn's access log is
  disabled (it prints full URLs); `httpx` is set to WARNING.

## 8. Frontend notes (`web/src/`)

* `lib/router.tsx`: a 70-line History-API router; focus moves to `#page-title` on navigation.
* `state/session.tsx`: session state; Overview and Ask render `key={activeDatasetId}`, so switching
  datasets remounts them (period, conversation, results and downloads reset). In-flight requests are
  aborted on unmount, and any response whose `dataset.id` is no longer active is discarded.
* `api/client.ts`: typed fetch wrapper; uploads use XHR for progress; errors become plain messages.
* Charts (`components/charts.tsx`) follow the data-viz rules used in this project: one y-axis, 2 px
  lines, ≤ 24 px bars with 4 px rounded ends and 2 px surface gaps, hairline solid grids, legends for
  2+ series, end labels only when they cannot collide, crosshair tooltips listing every series with the
  exact value first, and a table view for every chart. Series colours were checked with the palette
  validator (light surface): billed `#008a7a` / collected `#3cc4ab` (CVD ΔE 17.4, normal-vision ΔE
  17.5; collected is below 3:1 contrast, so legend, end label and table view carry identity);
  completed `#008a7a` / cancelled `#6250d6` / no-show `#eb6834` (worst adjacent CVD ΔE 19.0, all ≥ 3:1).
* Accessibility: skip link, landmarks, labelled controls, `aria-live` status for checking/answers,
  native `<dialog>` for confirmation, visible `:focus-visible` outline, `prefers-reduced-motion`.
* No uploaded rows are kept in `localStorage`.

## 9. Dependencies

Python (in `.venv`; `requirements.txt` direct, `requirements-lock.txt` full snapshot): FastAPI
0.162.4 (with Starlette 1.10.0), uvicorn 0.54.0, python-multipart 0.0.33, plus the original stack.
FastAPI 0.162 requires `opentelemetry-api`; only the no-op API package is installed (no SDK or
exporter), so nothing is sent anywhere.

Frontend (`web/package-lock.json` is committed; versions are exact). Each version was checked against
the npm registry on 11 Nov 2026 (exists, not deprecated, peer-compatible, Node 22 supported), and the
newest **stable release at least 7 days old** was chosen, so brand-new publishes are avoided:

| Package | Version | | Package | Version |
|---|---|---|---|---|
| react / react-dom / react-is | 19.3.1 | | vite | 8.3.5 |
| typescript | 7.0.2 | | @vitejs/plugin-react | 6.2.1 |
| tailwindcss / @tailwindcss/vite | 4.3.4 | | vitest | 5.1.0 |
| recharts | 3.10.1 | | @playwright/test | 1.64.1 |
| lucide-react | 1.67.0 | | @types/react, @types/react-dom | 19.3.0 |
| @types/node | 22.20.5 | | | |

To update: `npm view <pkg> time --json` to check release dates, `npm install --save-exact <pkg>@<v>`,
then run the full test list below. Browser tests use the installed Google Chrome (`channel: "chrome"`).

## 10. Tests

| Suite | Command | Covers |
|---|---|---|
| Original analytics (183) | `.venv/bin/python -m pytest tests --ignore=tests/web` | hand-checked metrics, tools, agent wiring, wording checks, Streamlit smoke |
| Import (`tests/web/test_ingest.py`) | `.venv/bin/python -m pytest tests/web` | both bundles' hand totals, mapping, ambiguous dates, exact money, blanks ≠ 0, duplicates, relationships, fee/payment consistency, review decisions, atomic failure, capability gating |
| API (`tests/web/test_api.py`, `test_ask.py`) | same | session isolation, CSRF header, host check, upload rejections, failed import keeps active dataset, overview totals, period clamping, switching, exports (selected dataset, formula-safe, negatives intact), retention (startup, sweep, on access), removal, templates, no implementation words in API text, scripted-model asking (no sample fallback, grounding, internals filtered, monthly, unavailable, clinical, busy, retry, service down, questions never logged) |
| Frontend unit | `cd web && npm test` | exact paise formatting, Indian grouping, axis ticks |
| Browser | `cd web && npm run e2e:offline` | 13 flows in Chrome, desktop and 390 px mobile |
| Live | `pytest -m integration`; `cd web && npm run e2e` | real llama3.2:3b on uploaded data; original 11-question suite |

## Verification log

Recorded on **11 Nov 2026** on the `migration/web-app` branch (MacBook Air M2, macOS 15, Python 3.13.5,
Node 22.22.2, Google Chrome via Playwright 1.64.1, Ollama with `llama3.2:3b`).

| Check | Command | Result |
|---|---|---|
| Offline Python tests | `.venv/bin/python -m pytest` | **272 passed** (183 original, unchanged; 89 new), 0 failed |
| Frontend type check | `npm run typecheck` (TypeScript 7.0.2) | **0 errors** |
| Frontend unit tests | `npm test` | **6 passed** |
| Production build | `npm run build` | **OK** (one ~690 KB bundle; warning limit raised, local app) |
| Browser checks, offline | `npm run e2e:offline` | **13 passed** |
| Browser check, live model | `npm run e2e` (live test) | **passed**: Sunrise "Which procedures generated the most billed revenue in 2025?" → Crown ₹23,000.00 in the answer, supporting table and downloaded CSV; Lakeview "What was billed revenue in 2024?" → ₹41,000.00, no Sunrise figures. Answers in 10.0 s and 5.1 s. |
| Live Python checks | `.venv/bin/python -m pytest -m integration` | **15 passed**: 4 web checks on uploaded data (billed revenue, monthly answer, outstanding on the second dataset, missing records explained) and the original 11-question suite on the sample data |
| Production mode | `./scripts/start.sh` | serves the built app on 127.0.0.1:8000 with CSP; chart renders; deep links reload; no console errors; path traversal returns the app page |
| Streamlit app | `streamlit run app.py` | starts and serves (`/_stcore/health` ok) |
| `npm audit` | | **0 vulnerabilities** |

Notes from this run:

* The first live run failed one original question (Q2, "Compare monthly billed revenue and
  collections in 2025") on the `billed_vs_collections_consistent` wording check. The answer was
  correct (it now cites the new monthly facts and states the ₹3,90,460.00 difference correctly); the
  check's 70-character window had cut the word "difference". Rule 3 now reads the whole clause as
  documented, the answer was added as a must-not-flag regression case, every must-flag case still
  fails as intended, and Q2 and then the full live suite passed.
* An early browser run took 34 minutes with two failures while a second Vite dev server shared the
  same dependency cache; the test server now uses its own cache and pre-bundles dependencies, and
  every later run took under a minute.
* Live results come from one model at temperature 0 on these phrasings; rephrased questions can behave
  differently. Calculated results, tables and downloads are authoritative.
