# Finfluencer & Health-Claim Auditor

Finfluencer & Health-Claim Auditor is a FastAPI application that audits claims made in public YouTube videos. It ingests video metadata and timestamped transcript segments, extracts a small set of finance, health, and other factual propositions, retrieves relevant evidence, and presents a claim-by-claim scorecard.

The application is evidence-first: it records when evidence is unavailable, marks predictions and opinions as `Unverifiable`, cites only evidence returned by the retrieval layer, and does not score or profile creators.

## Problem statement and goals

Finance and health videos often combine factual statements with forecasts, recommendations, personal opinions, statistics, and high-risk language. A viewer needs to know which statements are checkable, what was said and when, what sources were found, and how strongly those sources support the statement.

The project aims to:

- preserve the original quote and timestamp while providing an English claim representation;
- distinguish checkable factual claims from predictions, opinions, advice, and testimonials;
- retrieve relevant finance, health, news, scholarly, and general web evidence;
- apply source tiers and conservative verdict validation;
- make missing evidence visible instead of treating it as proof that a claim is false; and
- provide a local browser interface plus JSON and Markdown exports.

## Key features

- Accepts public YouTube watch, Shorts, live, and `youtu.be` URLs with valid 11-character video IDs.
- Fetches YouTube metadata and transcript data through SerpApi, retaining transcript timestamps and original wording.
- Uses Gemini structured output when configured to extract complete propositions, domains, claim types, entities, numeric expressions, and risk flags.
- Supports English, Hindi, and mixed Hindi-English/Hinglish transcript cases covered by the local tests. Other languages depend on usable transcript data and successful normalization.
- Falls back conservatively when the LLM is unavailable or structured output is invalid.
- Caps the final extracted shortlist at eight deduplicated claims.
- Routes retrieval by domain: finance uses Google Finance, Google News, and Google; health uses Google Scholar, Google News, and Google; other claims use Google News and Google.
- Retrieves, filters, deduplicates, ranks, and returns up to five evidence items per claim.
- Performs deterministic numeric comparisons when a claim and evidence contain comparable numeric values.
- Produces `Supported`, `Contradicted`, `Mixed`, `No evidence found`, or `Unverifiable` verdicts with low, medium, or high confidence and a neutral rationale.
- Streams audit progress over Server-Sent Events (SSE), persists audits and caches in SQLite, and supports JSON/Markdown export.
- Includes an offline/demo mode that reads cached responses only; it does not fabricate fixture responses.

## How the application works

1. The browser sends a YouTube URL to `POST /api/audits`. The API immediately creates an audit ID and returns HTTP `202` with status `pending`.
2. A background task ingests metadata and transcript segments through `app/ingest.py`.
3. `app/extract.py` chunks timestamped transcript segments, extracts and normalizes complete claims, removes duplicates, and keeps the highest-priority eight.
4. For every checkable claim, `app/retrieve.py` creates up to three targeted search requests, parses engine-specific responses, applies relevance checks and source tiers, and keeps at most five evidence records.
5. `app/numeric.py` checks comparable numeric claims. `app/judge.py` then applies deterministic rules and, when available, asks Gemini for a structured judgment restricted to the retrieved evidence.
6. Judgment validation removes invalid citation IDs and downgrades unsupported labels. The completed scorecard is saved in SQLite and can be read through the API.
7. The frontend listens to `/events`, falls back to polling when SSE is unavailable, renders claim cards and evidence, and links to JSON and Markdown exports.

## Technology stack

- Python 3.11 or newer (the current environment is Python 3.14.4)
- FastAPI, Pydantic v2, Uvicorn, and `python-dotenv`
- SQLite for audit, claim, LLM, and SerpApi response persistence/cache
- SerpApi via `requests` for YouTube data and evidence search
- Google Gemini via the `google-genai` package for structured extraction and optional judgment
- Vanilla HTML, CSS, and JavaScript frontend served by FastAPI
- Pytest for Python tests and Node's built-in test runner for frontend utility tests

## Project architecture

```text
.
├── app/
│   ├── main.py          FastAPI app, routes, SSE, exports, static-file mounting
│   ├── schemas.py       Pydantic request, transcript, claim, evidence, and scorecard models
│   ├── pipeline.py      Async audit orchestration and progress events
│   ├── ingest.py        YouTube URL parsing, metadata, and transcript normalization
│   ├── extract.py       Timestamp-aware claim extraction and normalization
│   ├── retrieve.py      Query drafting, search parsing, relevance, and evidence ranking
│   ├── judge.py         Verdict generation and citation/source-tier validation
│   ├── numeric.py       Numeric expression extraction and comparison
│   ├── serp.py          SerpApi client, retries, deterministic cache keys, and demo mode
│   ├── llm.py           Gemini provider and structured-output handling
│   ├── source_tiers.py  Domain-to-tier classification
│   └── db.py            SQLite schema, persistence, and cache helpers
├── config/source_tiers.yaml  Configured Tier 1–3 domains
├── web/                 Browser UI, styles, frontend utilities, and JS tests
├── tests/               Python unit, API, pipeline, retrieval, and regression tests
├── fixtures/            Cached SerpApi responses and transcript fixtures used by tests/demo work
├── eval/                Offline gold data, evaluation script, and results report
├── scripts/             Small maintenance/demo scripts
├── requirements.txt     Python dependencies
├── .env.example         Environment-variable template
└── pytest.ini           Pytest configuration
```

The SQLite database defaults to `data/auditor.sqlite3`. Database files are ignored by Git. The frontend is mounted from `web/` by `app/main.py` when that directory exists.

## Prerequisites

On Ubuntu/Linux, install:

- Python 3.11 or newer;
- `python3-venv` and `python3-pip`;
- Node.js 18 or newer only if you want to run the JavaScript tests; and
- Gemini and SerpApi credentials for live audits.

For Ubuntu, the system packages can be installed with:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm
```

The application itself has no `package.json`; JavaScript tests use Node's built-in test runner, so no `npm install` is required for the current frontend.

## Installation and setup on Ubuntu/Linux

From the repository root:

```bash
cd ~/proj-work-serpapi
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` locally and add your own credentials. Never commit `.env` or paste credentials into issue reports, README files, logs, or shell history. `.env` is ignored by Git; `.env.example` contains blank credential fields.

## Environment variables

The complete template is [`.env.example`](./.env.example). The application reads these variables:

| Variable | Purpose | Default/notes |
| --- | --- | --- |
| `LLM_PROVIDER` | Selects the LLM provider | Defaults to `gemini`; the current code supports Gemini only |
| `GEMINI_API_KEY` | Gemini authentication | Required for live LLM extraction/judging |
| `GEMINI_MODEL` | Gemini model name | Defaults to `gemini-3.5-flash`; choose a model available to your account |
| `SERPAPI_API_KEY` | SerpApi authentication | Required for uncached live metadata, transcript, and evidence requests |
| `DEMO_MODE` | Restricts SerpApi to the local cache | `0` by default; set to `1` to prevent live SerpApi calls |
| `AUDITOR_DB_PATH` | SQLite database path | Defaults to `data/auditor.sqlite3` |

A configured Gemini key is required for the full configured extraction/judgment path, but the pipeline can use its conservative deterministic fallbacks when a provider is unavailable. `DEMO_MODE=1` still requires matching cached responses for the requested engine and parameters; it does not create synthetic results.

## Run the application locally

With the virtual environment active and `.env` configured:

```bash
cd ~/proj-work-serpapi
source .venv/bin/activate
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/> in a browser. Check the service with:

```bash
curl http://127.0.0.1:8000/api/health
```

The health response includes `status`, the selected `llm_provider`, and whether `demo_mode` is enabled. Stop the server with `Ctrl+C`.

## Tests

Run the Python suite from the repository root:

```bash
source .venv/bin/activate
python -m pytest -q
```

Run the JavaScript tests with Node's built-in runner:

```bash
node --test web/app.test.mjs
```

The Python tests use temporary database paths through `tests/conftest.py` and mock external services, so the suite does not require live API calls. The evaluation script is a separate offline check and writes `eval/results.md`:

```bash
python eval/run_eval.py
```

## API endpoints

All application API routes are defined in [`app/main.py`](./app/main.py).

| Method and path | Behavior |
| --- | --- |
| `GET /api/health` | Returns service status, configured provider name, and demo-mode state. |
| `POST /api/audits` | Accepts JSON such as `{"url":"https://youtu.be/dQw4w9WgXcQ"}` and returns HTTP `202` with `{"audit_id":"...","status":"pending"}`. |
| `GET /api/audits/{audit_id}` | Returns the saved pending, complete, or failed audit scorecard. Unknown IDs return `404`. |
| `GET /api/audits/{audit_id}/events` | Streams progress events as `text/event-stream` until a `complete` or `failed` event. |
| `GET /api/audits/{audit_id}/export?format=json` | Returns the scorecard as JSON. |
| `GET /api/audits/{audit_id}/export?format=md` | Returns a Markdown export containing status, claim text, verdict, and timestamp. Other formats return `400`. |

Example request:

```bash
AUDIT_ID=$(curl -sS -X POST http://127.0.0.1:8000/api/audits \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://youtu.be/dQw4w9WgXcQ"}' | python -c 'import json,sys; print(json.load(sys.stdin)["audit_id"])')
curl -sS "http://127.0.0.1:8000/api/audits/${AUDIT_ID}"
```

For live progress, use `curl -N "http://127.0.0.1:8000/api/audits/${AUDIT_ID}/events"`. The frontend uses the same endpoint and falls back to status polling if the browser cannot keep an SSE connection.

## Evidence retrieval, analysis, source tiers, and scoring

### Evidence retrieval

Only claims marked `checkable` are sent to retrieval. Queries are created from the normalized claim, entities, numeric information, and domain. Retrieval parses engine responses, rejects empty or irrelevant results, filters some known off-domain results for finance claims, deduplicates by URL/title, and returns no more than five ranked evidence records.

Ranking prioritizes claim relevance, then a non-empty snippet, then source tier, then scholarly citation count where available. SerpApi responses are cached in SQLite using a deterministic engine/parameter key. API keys are removed from cache-key parameters and are not returned by the API.

### Claim analysis

Claims retain `original_text`, `normalized_text`, `start_seconds`, `end_seconds`, domain, claim type, entities, numeric information, and risk flags. Supported claim types include factual, historical, statistic, comparison, prediction, opinion, advice, and other categories. Predictions, opinions, advice, testimonials, and ambiguous/non-checkable items are not treated as factual checks.

The configured LLM is asked for structured JSON. The extraction code validates alignment to transcript segments, preserves original wording, deduplicates similar claims, and rejects unvalidated claims. Hindi and mixed-language claims are normalized to faithful English only when that normalization can be validated.

### Source tiers

The domain list is in [`config/source_tiers.yaml`](./config/source_tiers.yaml):

- **Tier 1:** regulators, government and health authorities, official filings/exchanges, peer-reviewed journals, recognized archives, and similar primary or authoritative sources;
- **Tier 2:** established financial/mainstream news outlets and recognized medical/health portals; and
- **Tier 3:** blogs, forums, social platforms, aggregators, video channels, and unverified websites.

The tier is a domain classification, not a guarantee that a page proves a claim. Relevance is evaluated before tier. A `Supported` or `Contradicted` result requires cited Tier 1 or Tier 2 evidence; Tier 3-only support is downgraded to `Mixed` during validation.

### Verdicts and numeric checks

The scorecard reports verdict counts rather than a single numerical truth score:

- `Supported`: relevant evidence confirms the claim;
- `Contradicted`: relevant evidence directly conflicts with the claim;
- `Mixed`: evidence conflicts, is partial, covers only some compound events, or does not meet the stronger support rules;
- `No evidence found`: no relevant indexed evidence survived retrieval and validation; and
- `Unverifiable`: the claim is a prediction, opinion, advice, testimonial, or other non-checkable statement.

Confidence is `Low`, `Medium`, or `High`. Numeric checks compare extracted values, units, ranges, and percentages with implementation-defined tolerances, and can provide a direct basis for a supported or contradicted judgment. Evidence IDs in a judgment are validated against the returned evidence list; hallucinated or missing IDs are removed.

These labels describe the retrieved material and implemented rules at audit time. They are not a guarantee of truth, completeness, or safety.

## Example workflow: audit a public YouTube URL

1. Start the server with `uvicorn app.main:app --reload`.
2. Open <http://127.0.0.1:8000/> and paste a public URL such as `https://www.youtube.com/watch?v=dQw4w9WgXcQ`.
3. Select **Audit video**. The browser creates an audit, displays live pipeline progress, and recovers by polling if SSE is unavailable.
4. Review the video metadata, claim timestamps, original quote, English claim, domain/type tags, risk flags, verdict, confidence, rationale, and cited evidence.
5. Use **Export JSON** or **Export Markdown** after completion.

For a terminal-only workflow, submit with the API example above, then request the audit ID until its status is `complete` or `failed`.

## Troubleshooting

- **`python3 -m venv` fails:** install the Ubuntu `python3-venv` package, then recreate the environment.
- **`ModuleNotFoundError` or `uvicorn: command not found`:** activate `.venv` and run `python -m pip install -r requirements.txt` again.
- **`GEMINI_API_KEY is not configured`:** confirm `.env` exists in the repository root, contains your local key, and that the server was restarted after editing it. Do not put the key in source code.
- **`SERPAPI_API_KEY is not configured`:** add a valid local SerpApi key for live requests, or set `DEMO_MODE=1` and use a request already represented in the local cache.
- **`Transcript unavailable for this video`:** the URL may be private, invalid, unsupported by the upstream response, or missing usable transcript segments.
- **Demo mode returns “No demo fixture cached”:** demo mode never calls SerpApi and only serves exact cache-key matches. Use a cached fixture/request or disable demo mode for live retrieval.
- **The browser reports “Service unavailable”:** verify Uvicorn is running on `127.0.0.1:8000`, then check `/api/health` and inspect the server terminal.
- **An audit remains pending:** request `GET /api/audits/{audit_id}`. The frontend already falls back from SSE to polling; a failed audit includes an `error` field.
- **Port 8000 is busy:** start Uvicorn on another port, for example `uvicorn app.main:app --reload --port 8001`, then open the matching URL.
- **JavaScript tests fail before running:** use Node.js 18 or newer and run `node --test web/app.test.mjs` from the repository root. There is no current `package.json`/npm test script.

## Security, privacy, and responsible use

- Keep `.env` private. Never commit API keys, passwords, or real credentials.
- The server enables permissive CORS (`*`) and is intended for local/development use; add authentication, restrictive origins, rate limiting, and production deployment controls before exposing it publicly.
- The application stores audit payloads, claims, and provider/search caches in the configured SQLite database. Choose `AUDITOR_DB_PATH` deliberately and protect the database file.
- External video metadata, transcripts, and search requests may be sent to YouTube/SerpApi and configured Gemini services. Avoid submitting private or sensitive material.
- Retrieved snippets and verdicts may be incomplete, stale, incorrectly interpreted, or wrong. A missing citation is not proof that a claim is false.
- This project is not financial or medical advice. Use qualified financial and medical professionals for decisions, diagnosis, or treatment.
- Do not use the output to harass creators, infer character or intent, or make high-impact decisions about people. The implemented analysis is claim-focused.

## Current limitations and future improvements

Current limitations visible in the implementation include:

- live data quality depends on SerpApi coverage, transcript availability, source snippets, and Gemini availability;
- source tiers classify domains and do not independently verify page content;
- only the configured Gemini provider is supported;
- the process-local SSE queue is not a durable distributed job system;
- the frontend is a lightweight static UI and the backend currently has permissive CORS with no authentication;
- the Markdown export is intentionally compact and does not include the full evidence payload; and
- the repository does not currently provide a package manager script for frontend testing or a production deployment configuration.

Potential future improvements are stronger authentication and deployment controls, durable job processing, richer evidence snapshots, more provider options, broader transcript/language coverage, direct page-content verification, configurable tier policies, and expanded evaluation against fresh real-world videos. These are not currently implemented.

## License

See [`LICENSE`](./LICENSE).
