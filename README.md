# Finfluencer & Health-Claim Auditor

**Evidence-first auditing of finance, health, and other factual claims in public YouTube videos.**

Finfluencer & Health-Claim Auditor is a FastAPI application that analyzes public YouTube videos and produces a timestamped, claim-by-claim evidence scorecard. It combines transcript ingestion, structured claim extraction, targeted web research, source-quality classification, numeric comparisons, and conservative verdict validation.

Instead of assigning a simplistic truth score to an entire video, the application examines individual statements, preserves their original context, identifies relevant evidence, and makes missing evidence visible.

**Core principles**
- Analyze claims, not creators.
- Preserve original wording and timestamps.
- Distinguish checkable facts from predictions, opinions, advice, and testimonials.
- Cite only evidence returned by the retrieval pipeline.
- Treat missing evidence as insufficient evidence, not proof of falsity.
- Use conservative verdicts when evidence or the configured language model is unavailable.

## Table of contents

- [Quick start](#quick-start)
- [Problem statement and goals](#problem-statement-and-goals)
- [Key features](#key-features)
- [How it works](#how-it-works)
- [Technology stack](#technology-stack)
- [Project architecture](#project-architecture)
- [Prerequisites](#prerequisites)
- [Installation and configuration](#installation-and-configuration)
- [Running the application](#running-the-application)
- [Tests and evaluation](#tests-and-evaluation)
- [API reference](#api-reference)
- [Evidence retrieval and scoring](#evidence-retrieval-and-scoring)
- [Example workflow](#example-workflow)
- [Troubleshooting](#troubleshooting)
- [Security, privacy, and responsible use](#security-privacy-and-responsible-use)
- [Limitations and future work](#limitations-and-future-work)
- [License](#license)

## Quick start

### Requirements

- Python 3.11 or newer, subject to dependency compatibility.
- A SerpApi API key for uncached live YouTube and evidence requests.
- A Gemini API key for the configured LLM extraction and judgment workflow.
- Node.js 18 or newer only if you want to run the JavaScript tests.

### 1. Clone the repository

```bash
git clone https://github.com/FinfluencerAuditor/finfluencer-auditor.git
cd finfluencer-auditor
```

### 2. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` locally and provide your own Gemini and SerpApi credentials. Never commit `.env` or share API keys in source code, screenshots, logs, or issue reports.

### 4. Start the application

```bash
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000/** in your browser.

Check the service health at **http://127.0.0.1:8000/api/health**.

To use port 8011 instead:

```bash
uvicorn app.main:app --reload --port 8011
```

Then open http://127.0.0.1:8011/.

## Problem statement and goals

Finance and health videos frequently combine verifiable statements with forecasts, recommendations, personal opinions, statistics, and high-risk claims. Viewers need a way to identify what was actually said, when it was said, which sources are relevant, and how strongly those sources support the statement.

This project aims to:

- Preserve original quotations and timestamps while providing a normalized English representation when reliable normalization is possible.
- Distinguish factual claims from predictions, opinions, advice, testimonials, and other non-checkable statements.
- Retrieve relevant financial, news, scholarly, health, and general web evidence.
- Classify sources into configurable quality tiers.
- Apply numeric comparisons and conservative verdict validation.
- Expose missing or insufficient evidence rather than silently treating it as confirmation or contradiction.
- Provide a browser-based interface and JSON and Markdown exports.

## Key features

- **YouTube ingestion:** Accepts public YouTube watch, Shorts, live, and `youtu.be` URLs with valid 11-character video IDs.
- **Timestamped transcripts:** Retrieves metadata and transcript data through SerpApi and preserves transcript timestamps and original wording.
- **Structured claim extraction:** Uses Gemini structured output when configured to identify complete propositions, domains, claim types, entities, numeric expressions, and risk flags.
- **Multilingual handling:** Supports English, Hindi, and mixed Hindi-English/Hinglish cases covered by the local tests. Other languages depend on transcript availability and successful normalization.
- **Conservative fallback behavior:** Continues with deterministic fallbacks when the LLM is unavailable or its structured output is invalid.
- **Bounded claim selection:** Keeps a final shortlist of up to eight deduplicated claims.
- **Domain-aware retrieval:** Selects search engines according to claim domain and type, rather than applying the same financial search strategy to every finance-related statement.
- **Evidence filtering and ranking:** Filters, deduplicates, and ranks retrieved evidence before it reaches the judging stage.
- **Numeric verification:** Compares compatible numeric expressions when the claim and evidence contain comparable values.
- **Conservative verdicts:** Produces Supported, Contradicted, Mixed, No evidence found, or Unverifiable labels with confidence levels and rationales.
- **Live progress:** Streams audit progress using Server-Sent Events (SSE), with frontend polling as a fallback.
- **Persistent results:** Stores audits and cache entries in SQLite.
- **Export support:** Offers JSON and Markdown scorecard exports.
- **Offline/demo mode:** Uses matching cached SerpApi responses without making live SerpApi requests or fabricating fixture results.
- **Automated tests:** Includes Python tests and JavaScript utility tests.

## How it works

1. The browser submits a public YouTube URL to `POST /api/audits`.
2. The API creates an audit identifier and returns HTTP 202 with a pending status.
3. `app/ingest.py` retrieves video metadata and transcript segments through SerpApi.
4. `app/extract.py` processes timestamped transcript segments, extracts complete claims, normalizes them, removes duplicates, and selects the highest-priority claims.
5. Checkable claims are passed to `app/retrieve.py`, which generates targeted queries, calls the configured search engines, parses responses, applies relevance checks, and ranks eligible evidence.
6. `app/numeric.py` performs deterministic comparisons where numeric expressions can be compared meaningfully.
7. `app/judge.py` applies deterministic verdict rules and, when available, requests a structured judgment from Gemini using the retrieved evidence.
8. Validation removes invalid evidence references and downgrades unsupported verdicts.
9. The completed scorecard is persisted in SQLite and returned through the API.
10. The frontend displays the claim-by-claim results, listens for progress events, and provides export options.

## Technology stack

| Component | Technology |
|---|---|
| Backend | Python, FastAPI, Uvicorn |
| Validation and schemas | Pydantic v2 |
| Transcript and evidence retrieval | SerpApi via `requests` |
| LLM | Google Gemini through `google-genai` |
| Persistence and caching | SQLite |
| Configuration | `python-dotenv` |
| Frontend | HTML, CSS, vanilla JavaScript |
| Backend tests | Pytest |
| Frontend tests | Node.js built-in test runner |

## Project architecture

```text
finfluencer-auditor/
├── app/
│   ├── main.py          # FastAPI routes, SSE, exports, static files
│   ├── schemas.py       # Request, transcript, claim, evidence, scorecard models
│   ├── pipeline.py      # Asynchronous audit orchestration and progress
│   ├── ingest.py        # URL parsing, metadata, transcript normalization
│   ├── extract.py       # Timestamp-aware claim extraction and normalization
│   ├── retrieve.py      # Query drafting, search parsing, evidence ranking
│   ├── judge.py         # Verdict generation and evidence validation
│   ├── numeric.py       # Numeric expression extraction and comparison
│   ├── serp.py          # SerpApi client, retries, caching, demo mode
│   ├── llm.py           # Gemini provider and structured-output handling
│   ├── source_tiers.py  # Source-tier classification
│   └── db.py            # SQLite persistence and cache helpers
├── config/
│   └── source_tiers.yaml
├── web/                 # Browser interface, styles, frontend utilities
├── tests/               # Unit, API, pipeline, retrieval, regression tests
├── fixtures/            # Cached responses and test/demo fixtures
├── eval/                # Offline evaluation and benchmark scripts
├── scripts/             # Maintenance and demonstration scripts
├── requirements.txt
├── .env.example
├── .gitignore
└── pytest.ini
```

The default SQLite database path is `data/auditor.sqlite3`. Database files should remain local and ignored by Git. The frontend is served by `app/main.py` when the `web/` directory is present.

## Prerequisites

On Ubuntu/Linux, install Python, virtual-environment support, and pip:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

Install Node.js 18 or newer if you want to run the frontend tests. The frontend currently uses Node's built-in test runner and does not require a `package.json` or an `npm install` step.

## Installation and configuration

### Environment variables

The `.env.example` file documents the supported environment variables.

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | Selects the LLM provider; the current implementation supports Gemini. |
| `GEMINI_API_KEY` | Gemini authentication for the configured LLM workflow. |
| `GEMINI_MODEL` | Gemini model identifier configured for the application. |
| `SERPAPI_API_KEY` | SerpApi authentication for uncached live requests. |
| `DEMO_MODE` | Set to `1` to disable live SerpApi requests and use matching cached responses only. |
| `AUDITOR_DB_PATH` | SQLite database path; defaults to `data/auditor.sqlite3`. |

The example environment template supplies the current configured defaults. Check `.env.example` and `app/llm.py` for the exact Gemini model identifier used by your checkout.

A Gemini key is required for the configured live LLM workflow. If Gemini is unavailable, the pipeline can use conservative deterministic fallbacks, but results may be less complete.

A SerpApi key is required for uncached live metadata, transcript, and evidence requests. In demo mode, matching cached responses must exist for the requested engine and parameters; the application does not generate synthetic search results.

## Running the application

Activate the virtual environment and start the server:

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/ and check the service:

```bash
curl http://127.0.0.1:8000/api/health
```

The health endpoint reports the service status, selected LLM provider, and demo-mode state.

Stop the development server with `Ctrl+C`.

## Tests and evaluation

Run the Python test suite:

```bash
source .venv/bin/activate
python -m pytest -q
```

Run the JavaScript tests:

```bash
node --test web/app.test.mjs
```

The Python tests use isolated or temporary database paths and mock external services where appropriate, so the unit and regression suite should not require live API calls.

The latest local test run during development completed with **153 tests passing**. This is a test-suite result, not a claim of 100% real-world fact-checking accuracy.

Run the offline evaluation script separately:

```bash
python eval/run_eval.py
```

The evaluation script writes its report to `eval/results.md`. Evaluation results depend on the test cases and criteria included in the repository and should not be interpreted as a guarantee of real-world accuracy.

## API reference

Application routes are defined in `app/main.py`.

| Method and path | Behavior |
|---|---|
| `GET /api/health` | Returns service status, configured provider, and demo-mode state. |
| `POST /api/audits` | Accepts a video URL and creates a pending audit. |
| `GET /api/audits/{audit_id}` | Returns the saved audit status and scorecard. Unknown IDs return 404. |
| `GET /api/audits/{audit_id}/events` | Streams audit progress as `text/event-stream`. |
| `GET /api/audits/{audit_id}/export?format=json` | Exports the scorecard as JSON. |
| `GET /api/audits/{audit_id}/export?format=md` | Exports a compact Markdown scorecard. Unsupported formats return 400. |

### Example API request

Submit a video for auditing:

```bash
AUDIT_ID=$(curl -sS -X POST http://127.0.0.1:8000/api/audits \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://youtu.be/dQw4w9WgXcQ"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["audit_id"])')

echo "$AUDIT_ID"
```

The response contains an audit ID and a pending status. Retrieve the current result:

```bash
curl -sS "http://127.0.0.1:8000/api/audits/${AUDIT_ID}"
```

Stream live progress:

```bash
curl -N "http://127.0.0.1:8000/api/audits/${AUDIT_ID}/events"
```

Export the result:

```bash
curl -sS \
  "http://127.0.0.1:8000/api/audits/${AUDIT_ID}/export?format=json"
```

For Markdown, replace `format=json` with `format=md`.

Use a public video URL for testing. The example video ID above is illustrative; successful auditing depends on transcript availability and the upstream services.

## Evidence retrieval and scoring

### Evidence retrieval

Only claims marked as checkable are sent to evidence retrieval. Queries are based on the normalized claim, relevant entities, numeric details, and domain.

The retrieval pipeline parses engine-specific responses, rejects empty or irrelevant results, filters certain known off-domain results for finance claims, deduplicates by URL or title, and ranks eligible evidence. The pipeline's per-claim evidence limit is enforced in the implementation.

Search routing is claim-aware:

- **Current finance quotes and metrics:** Google Finance, Google News, and Google.
- **Historical returns, fund studies, fee comparisons, and broader finance assertions:** Google News and Google.
- **Health claims:** Google Scholar, Google News, and Google.
- **Other factual claims:** Google News and Google.

The exact routes and eligible result counts are determined by the retrieval implementation. A search-engine response is a candidate source, not proof that a claim is true.

SerpApi responses are cached in SQLite using deterministic keys derived from the engine and request parameters. API keys are excluded from cache-key parameters and are not returned through the application's API.

### Claim analysis

Claims retain information such as:

- Original transcript wording.
- Normalized claim text.
- Start and end timestamps.
- Domain and claim type.
- Relevant entities and numeric expressions.
- Risk flags.

Supported claim categories include factual, historical, statistic, comparison, prediction, opinion, advice, and other categories.

Predictions, opinions, advice, testimonials, and ambiguous or non-checkable statements should not be treated as ordinary factual checks.

The extraction pipeline validates alignment with transcript segments, preserves original wording, deduplicates similar claims, and rejects claims that fail validation. Hindi and mixed-language claims are normalized into English only when the normalization can be validated.

### Source tiers

Source classifications are configured in `config/source_tiers.yaml`.

- **Tier 1:** Regulators, government and health authorities, official filings and exchanges, peer-reviewed journals, recognized archives, and other authoritative primary sources.
- **Tier 2:** Established financial and mainstream news outlets and recognized medical or health portals.
- **Tier 3:** Blogs, forums, social platforms, aggregators, video channels, and unverified websites.

A tier describes the classification of a source's domain; it does not guarantee that the page proves a particular claim. Relevance is assessed separately.

Under the current validation rules, a Supported or Contradicted verdict requires eligible Tier 1 or Tier 2 evidence. Support based only on Tier 3 evidence is downgraded during validation.

### Verdicts and numeric checks

The scorecard reports claim-level verdicts rather than a single numerical truth score.

| Verdict | Meaning |
|---|---|
| **Supported** | Retrieved evidence sufficiently supports the claim under the implemented rules. |
| **Contradicted** | Retrieved evidence directly conflicts with the claim under the implemented rules. |
| **Mixed** | Evidence is partial, conflicting, covers only part of a compound claim, or fails the stronger support requirements. |
| **No evidence found** | No relevant evidence survived retrieval and validation. This does not establish that the claim is false. |
| **Unverifiable** | The statement is a prediction, opinion, advice, testimonial, or another non-checkable claim. |

Confidence is reported as Low, Medium, or High.

Numeric checks compare extracted values, units, ranges, and percentages when they are meaningfully comparable. Implementation-defined tolerances may affect whether a comparison is considered a match or conflict.

Evidence IDs are checked against the evidence returned by retrieval. Invalid or missing IDs are removed, and unsupported verdicts are downgraded during validation.

All verdicts describe the evidence retrieved and the rules applied at audit time. They are not guarantees of truth, completeness, or safety.

## Example workflow: audit a public YouTube video

1. Start the application using Uvicorn.
2. Open the local browser interface.
3. Paste a public YouTube URL and select **Audit video**.
4. Follow the pipeline progress as metadata, transcript segments, claims, evidence, and judgments are processed.
5. Review the claim timestamps, original quotations, normalized English text, domain and type labels, risk flags, verdicts, confidence, rationales, and citations.
6. Export the completed scorecard as JSON or Markdown.

The frontend listens for SSE progress events and falls back to polling when a persistent event connection is unavailable.

For terminal-only usage, submit a video through `POST /api/audits`, save the returned audit ID, and request the audit endpoint until processing is complete or failed.

## Troubleshooting

**Virtual-environment creation fails**

Install the Ubuntu `python3-venv` package and retry.

**`ModuleNotFoundError` or `uvicorn: command not found`**

Activate `.venv` and install the requirements again:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

**Gemini key is missing**

Check that `.env` exists in the repository root, contains your local key, and that you restarted the server after editing it. Never put the key in source code.

**SerpApi key is missing**

Add a valid key to `.env` for live requests, or use `DEMO_MODE=1` with an exact matching cached request.

**Transcript unavailable**

The video may be private, invalid, unsupported by the upstream response, or missing usable transcript segments.

**No demo fixture is cached**

Demo mode does not call SerpApi. Use a request represented by a matching cached response or disable demo mode for live retrieval.

**Browser reports service unavailable**

Verify that Uvicorn is running on the port in the browser URL. Check `/api/health` and inspect the server terminal.

**Audit remains pending**

Request `GET /api/audits/{audit_id}` to check its status. The frontend uses polling if SSE is unavailable. A failed audit may include an error field.

**Port 8000 is busy**

Run Uvicorn on another port:

```bash
uvicorn app.main:app --reload --port 8011
```

Then open http://127.0.0.1:8011/.

**JavaScript tests fail before running**

Install Node.js 18 or newer and run the tests from the repository root:

```bash
node --test web/app.test.mjs
```

The current frontend does not require a `package.json` or an npm test script.

## Security, privacy, and responsible use

- Keep `.env` private. Never commit API keys, passwords, or real credentials.
- Rotate any credential that may have been exposed. Removing a credential from the latest version does not make an exposed credential safe to reuse.
- The server currently enables permissive CORS (`*`) and is intended for local or development use. Add authentication, restrictive origins, rate limiting, and production deployment controls before exposing it publicly.
- Audit payloads, claims, and provider/search caches may be stored in SQLite. Configure `AUDITOR_DB_PATH` deliberately and protect the database file.
- External video metadata, transcripts, and search requests may be sent to YouTube/SerpApi and configured Gemini services. Avoid submitting private or sensitive material.
- Retrieved snippets and verdicts may be incomplete, stale, incorrectly interpreted, or wrong. A missing citation is not proof that a claim is false.
- This project is not financial or medical advice. Consult qualified financial and medical professionals for decisions, diagnosis, or treatment.
- Do not use the output to harass creators, infer character or intent, or make high-impact decisions about people. The implemented analysis is claim-focused.

## Limitations and future work

### Current limitations

- Live data quality depends on SerpApi coverage, transcript availability, source snippets, and Gemini availability.
- Source tiers classify domains and do not independently verify page content.
- Only the configured Gemini provider is supported.
- The process-local SSE queue is not a durable distributed job system.
- The frontend is a lightweight static interface.
- The backend currently has permissive CORS and no authentication.
- Markdown exports are intentionally compact and do not contain the complete evidence payload.
- The repository does not currently provide a frontend package-manager script or a production deployment configuration.
- Language coverage and transcript normalization depend on the available data and validation success.
- Search results may not include every relevant source, and a lack of indexed evidence must not be interpreted as proof of falsity.

### Potential future improvements

- Authentication and stronger deployment controls.
- Durable background-job processing and scalable progress delivery.
- Richer evidence snapshots and direct page-content verification.
- Additional LLM providers and configurable provider selection.
- Broader transcript and language coverage.
- Configurable source-tier policies.
- Expanded evaluation against fresh real-world videos.
- Improved evidence quality measurement and reproducible audit reports.

These improvements are potential future work and should not be considered implemented features.

## License

See [LICENSE](LICENSE) for the project's licensing terms.
