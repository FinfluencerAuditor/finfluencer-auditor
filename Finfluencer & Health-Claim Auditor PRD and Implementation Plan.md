# Finfluencer & Health-Claim Auditor

*Product Requirements Document and Implementation Plan · SerpApi India Hackathon 2026 · Track: Open Innovation*

## 1. Summary

**One line:** paste a YouTube link and get a timestamped, claim-by-claim scorecard showing which statements in the video are backed by evidence, contradicted by it, or simply unverifiable, with live sources from SerpApi.

**What it does:**

- Pulls the video transcript with timestamps.
- Uses an LLM to extract specific, checkable claims (financial and health).
- Routes each claim to the right search engines: Google News, Google Scholar, Google Finance, Google Search.
- Judges each claim against retrieved evidence only.
- Shows a scorecard where every claim links back to the exact moment in the video.

**Why it is different:** existing fact-checkers work on articles, headlines or live debates. Nothing in the BuiltWithSerpApi gallery audits *video*, and video is where Indian finfluencers and health influencers reach most people.

**Honesty principle:** the tool never invents evidence. If search finds nothing, the verdict is “No evidence found”, not a guess. Predictions (“this stock will double”) are labelled unverifiable and flagged as high-risk language, not judged true or false.

## 2. Hackathon Requirements Checklist

Taken from the official hackathon page. Re-check against the Rules page before submitting; the published Rules and Terms are authoritative.

- **Deadline:** the hackathon website says **October 10, 2026, 23:59 IST**. The launch blog post and a community page said **October 5**. Confirm the date shown on the submission dashboard today, or email the organiser (adarsh@serpapi.com). Plan to submit by 18:00 IST on Oct 10 at the very latest, and save a draft early.
- **Eligibility:** resident of India, 18 or older, solo or team of up to five. Any language or stack.
- **Public GitHub repository** with clear setup instructions.
- **Demo video under 3 minutes**, showing the project running locally; public or unlisted link that opens without login (test in a private window). Production quality does not affect judging.
- **Project description:** what it does, who it helps, how it uses SerpApi. Choose one track.
- **Participant details:** lead's name, email, phone, occupation, years of experience; teammates' names and emails.
- **Disclosures:** whether the project already existed, and which AI tools were used.
- **Accept Rules and Terms**, including permissions for any code or content you submit (use only code and content you are allowed to use; add a LICENSE; never commit API keys).
- **Prizes:** one competitive award per project; every valid submission gets 1,000 SerpApi credits.
- **Track note:** Open Innovation is described as a wildcard for ideas that do not fit the other tracks. This project could also fit Knowledge & Public Interest (news literacy). To justify Open Innovation, describe it as a creative consumer tool for auditing video, and keep the optional browser-extension stretch goal if time allows. Describe the primary purpose accurately in the submission.

## 3. Problem and Opportunity

- Millions of Indians take money and health decisions from YouTube creators. Claims are fast, confident and rarely sourced.
- Verifying a 20-minute video by hand means rewatching it, noting claims, and searching each one. Nobody does this.
- Existing tools check text. A viewer has no way to ask “which statements in this video are actually supported?”
- Live search data makes it possible to check claims against current news, research and market data in under two minutes.

## 4. Target Users

- **Retail investor (primary):** 22 to 35, follows stock and mutual-fund creators, wants to sanity-check a tip before acting.
- **Family health-video forwarder (primary):** receives “miracle remedy” videos on WhatsApp and wants a quick, sourced reality check.
- **Journalist or fact-checker (secondary):** needs a fast first pass over a long video with timestamps to cite.
- **Creator (secondary):** wants to check their own script before publishing.

## 5. Goals, Non-Goals and Success Metrics

**Goals**

- G1: Turn a YouTube URL into a sourced scorecard in under 2 minutes for a typical 10 to 20 minute video.
- G2: Every claim shows its timestamp, the quoted line, a verdict, a short rationale and at least one source (or an explicit “none found”).
- G3: Make the product's reliance on live search data obvious in both the UI and the demo.
- G4: Be safe by design: neutral labels, visible evidence, clear disclaimers.

**Non-goals**

- No investment or medical advice, and no buy/sell signals.
- No judging of creators' intent, honesty or legality, and no “fraud score”.
- No fact-checking of opinions or predictions.
- No account system, payments or mobile app for the hackathon.

**Success metrics (targets for the build)**

- End-to-end run time under 120 seconds on a 15-minute video.
- Gold set of 5 hand-labelled videos: at least 80% of claims a human marked as checkable are extracted, and at least 70% verdict agreement with the human labels. Report the real numbers in the README, whatever they turn out to be.
- Zero verdicts that cite a source not actually retrieved (enforced in code).
- Demo shows a full live run in under 3 minutes.

## 6. Scope and Features

**P0: must ship**

- URL input and validation (watch, short and youtu.be formats).
- Transcript ingestion with timestamps, plus video metadata (title, channel, publish date, description).
- Hinglish and Hindi handling: detect the transcript language and normalise to English for extraction while keeping original timestamps and the original quote.
- Claim extraction with structured output (see section 12).
- Domain router: finance claims to Finance + News + Search; health claims to Scholar + News + Search.
- Evidence retrieval with source-tier ranking.
- Verdict engine with five labels and rationale.
- Scorecard UI with timestamp deep links (youtu.be link with the start time), evidence list and filters by verdict.
- Progress streaming so the demo shows the pipeline working live.
- Disclaimer banner and README with setup steps.

**P1: should ship**

- Risk-language flags (“guaranteed”, “risk-free”, “100% cure”, “double your money”, “doctors hide this”) independent of the verdict.
- Deterministic numeric checker for finance claims (price, market cap, P/E, 52-week range, dividend yield) against fields actually returned by the Finance engine.
- Timeline bar across the video, coloured by verdict, showing where claims cluster.
- SQLite cache for every SerpApi call and a **demo mode** that replays cached responses so the demo and tests never depend on live quota.
- Export scorecard as Markdown or JSON.

**P2: stretch**

- Chrome extension side panel that audits the video you are watching.
- Compare two videos on the same topic.
- Search for the creator's regulator-registration mentions as a context signal only, never a verdict.

## 7. User Flow

1. User pastes a YouTube link and clicks **Audit**.
2. A progress panel streams the steps: fetching transcript, extracting claims, searching evidence, judging.
3. The scorecard appears: a summary header, a timeline bar and claim cards.
4. User clicks a timestamp to jump to that moment on YouTube, expands a card for evidence, and exports the result.

**Summary header:** video title and channel, number of claims found, counts per verdict, and a count of high-risk-language flags. Avoid a single “trust score” for the creator; show counts, not a grade.

**Claim card:** timestamp link, quoted line (original language) and English normalisation, domain badge (Finance or Health), verdict badge, one to three sentence rationale, evidence list (source name, tier, date, snippet, link), and any risk-language flags.

## 8. Verdict Taxonomy and Rules

- **Supported:** at least one Tier 1 or Tier 2 source clearly supports the claim and nothing credible contradicts it.
- **Contradicted:** a credible source directly contradicts the claim.
- **Mixed:** credible sources disagree, or support only part of the claim (for example, evidence in animals only, or a claim true for one period but not the current one).
- **No evidence found:** retrieval ran but returned nothing relevant. This is not the same as false.
- **Unverifiable:** predictions, guarantees, personal testimonials and opinions. Always shown with the risk-language flag where relevant.

**Hard rules**

- The judge may only cite evidence IDs that were retrieved for that claim; any other ID is discarded in code.
- If fewer than one relevant evidence item exists, the verdict cannot be Supported or Contradicted.
- Every verdict carries a confidence of Low, Medium or High; Low is shown visibly.
- Source tiers: Tier 1 regulators, government and health bodies, peer-reviewed papers, exchange filings; Tier 2 established news outlets; Tier 3 everything else (shown but never sole basis for Supported or Contradicted). Keep the tier list in a config file the user can edit.

## 9. How SerpApi Powers the Product

Search data is the core of the product; without live retrieval there are no verdicts.

- **YouTube Video Transcript API:** timestamped transcript, the backbone of the product.
- **YouTube Video API:** title, channel, description and publish date. The publish date matters: a claim about “this year's” budget is judged against the right year.
- **Google News API:** recent reporting, regulator actions, company events and health advisories.
- **Google Scholar API:** peer-reviewed evidence for health claims; titles, snippets, citation counts and years help rank evidence.
- **Google Finance API:** quote and key statistics for a ticker, used by the numeric checker. Confirm the ticker format for Indian stocks (for example symbol plus exchange such as NSE or BSE) in the SerpApi playground.
- **Google Search API:** targeted queries for regulator and health-body pages (for example a regulator name plus the entity, or an institute name plus the ingredient and condition) and for anything the other engines miss.

Before writing integration code, run one example of each engine in the SerpApi playground and save the raw JSON as test fixtures. Confirm exact parameter names and response fields in the official docs rather than assuming them.

**Search budget.** The free plan gives 250 searches per month, so budget carefully.

- Per video: 2 calls (metadata and transcript) + up to 8 claims × about 3 calls = roughly 26 calls.
- Cap at 8 checkable claims per video (highest-risk first) and at 3 searches per claim.
- Cache every call by engine and parameters in SQLite; never repeat a call during development.
- Develop against saved fixtures; spend live calls only on the gold-set videos and the final demo run. Five gold videos cost about 130 calls, leaving room for debugging.

## 10. System Architecture

Pipeline, with each stage a separate, testable module:

1. **Ingest:** parse URL to video ID; fetch metadata and transcript; detect language; if not English, normalise to English segment by segment, keeping the original text and timestamps.
2. **Chunk:** group transcript segments into windows of roughly 2 to 3 minutes with a small overlap, each keeping its start and end timestamps.
3. **Extract:** the LLM returns structured claims per window (section 12). A second pass de-duplicates repeated claims and ranks by risk and checkability; keep the top 8.
4. **Route and query:** a rules-based router sends each claim to engines by domain, and the LLM drafts one to three short search queries per claim (entity-specific, no filler words).
5. **Retrieve and rank:** run queries, drop duplicates, tag source tier, keep the top 5 evidence items per claim.
6. **Check numbers (P1):** for finance claims with numeric statements about a listed company, compare against Finance engine fields within a tolerance and attach the result as evidence.
7. **Judge:** the LLM receives the claim, the video publish date and only the retrieved evidence, and returns a verdict in a fixed JSON schema; a validator enforces the hard rules from section 8.
8. **Assemble and stream:** write results to the database and stream progress events to the UI.

Design choices that matter for judges: run claim checks concurrently with a worker pool, retry transient failures with backoff, and degrade gracefully (a failed claim shows “could not check” and does not break the page).

## 11. Data Model and API

**Tables (SQLite)**

- `audits`: id, video\_id, title, channel, published\_at, language, status, created\_at.
- `claims`: id, audit\_id, start\_seconds, end\_seconds, quote\_original, claim\_english, domain, claim\_type, entities (JSON), risk\_flags (JSON), priority.
- `evidence`: id, claim\_id, engine, title, source, tier, date, snippet, url.
- `verdicts`: claim\_id, label, confidence, rationale, evidence\_ids (JSON).
- `api_cache`: key (engine plus sorted params), response JSON, fetched\_at.

**Endpoints (FastAPI)**

- `POST /api/audits` with the URL; returns an audit ID.
- `GET /api/audits/{id}/events` as a server-sent event stream of progress.
- `GET /api/audits/{id}` returns the full scorecard.
- `GET /api/audits/{id}/export?format=md|json`.
- `GET /api/health` and a `DEMO_MODE` environment flag for cached replay.

## 12. Prompt Design

**Claim extraction (per window).** Instruct the model to return JSON only, with these fields for each claim: `quote_original`, `claim_english`, `start_seconds`, `domain` (finance, health or other), `claim_type` (verifiable\_fact, prediction, advice, testimonial, opinion), `entities` (company, ticker if stated, ingredient, condition, regulator), `risk_language` (list of matched phrases) and `checkable` (true or false). Rules to state in the prompt: extract only claims a viewer might act on; one claim per object; keep the speaker's meaning, do not strengthen or soften it; mark predictions and guarantees as not checkable; ignore greetings, ads and filler; never add facts that are not in the transcript.

**Query drafting.** Given a claim, return one to three search queries per engine, using the entity names and the specific assertion. Include the video's publish year when the claim is time-bound.

**Verdict judge.** Provide the claim, the publish date and a numbered evidence list. State plainly: use only the evidence provided; if the evidence does not address the claim, return No evidence found; cite evidence by ID; prefer higher-tier sources; explain disagreements as Mixed; return label, confidence, a rationale of at most three sentences, and evidence IDs. Temperature low. Add two or three few-shot examples, including one No evidence found example and one prediction.

**Model choice.** Keep the LLM provider behind a small interface so you can use whichever API or local model you have access to. Whichever you use, list it in the AI-tools disclosure.

## 13. Tech Stack and Repository

**Stack:** Python 3.11+, FastAPI, SQLite, the official SerpApi Python library, an LLM client behind an interface, and a lightweight frontend (plain HTML with a little JavaScript, or a small React app). Prefer the simplest frontend you can finish; the scorecard design matters more than the framework.

```
finfluencer-auditor/
  README.md            # setup, usage, architecture, accuracy results
  LICENSE
  .env.example         # SERPAPI_API_KEY, LLM key, DEMO_MODE
  app/
    main.py            # FastAPI app and routes
    pipeline.py        # orchestration
    ingest.py          # URL parsing, transcript, metadata, normalisation
    extract.py         # claim extraction and de-duplication
    retrieve.py        # engine calls, caching, tiering
    numeric.py         # finance numeric checks
    judge.py           # verdict prompt and validator
    llm.py             # provider interface
    db.py
    config/source_tiers.yaml
  web/                 # index.html, scorecard UI
  fixtures/            # saved SerpApi responses for demo mode and tests
  eval/                # gold-set labels and evaluation script
  tests/
```

## 14. Quality and Evaluation

- **Gold set:** pick 5 public videos (2 finance, 2 health, 1 mixed), and hand-label the checkable claims and a verdict for each. Run the evaluation script and publish the numbers in the README, including failures. Honest results build credibility.
- **Unit tests:** URL parsing, transcript chunking, evidence-ID validation, numeric tolerance logic, risk-language matching.
- **Failure tests:** captions disabled, very long video, non-English transcript, engine timeout, empty search results.
- **Manual review:** read every verdict in the demo video before recording.

## 15. Risks and Mitigations

- **Wrong or overconfident verdicts.** Evidence-only judging, enforced citation validation, visible confidence, and “No evidence found” as a first-class outcome.
- **Defamation and fairness.** Judge claims, not people; no creator score; neutral labels; a disclaimer that verdicts reflect retrieved evidence at the time of the audit. Pick demo videos carefully: prefer your own recording, a consenting creator, or clearly educational content. Do not showcase a named creator as a bad actor.
- **Medical and financial harm.** A clear banner: this is not medical or financial advice. Never recommend actions.
- **Transcript quality.** Auto-captions in Hinglish are noisy. Normalise with the LLM, show the original quote, and let the user see both.
- **Quota exhaustion.** Caching, fixtures, demo mode, per-video caps.
- **Coverage gaps.** The Finance engine may not return every field for every Indian ticker; the numeric checker only runs on fields that exist and otherwise falls back to News and Search.
- **LLM cost or rate limits.** Batch windows, keep prompts short, cache LLM outputs per transcript hash.
- **Deadline.** Scope cuts are pre-agreed: drop P2 first, then the timeline bar, then the numeric checker.

## 16. Implementation Plan

Today is Thursday, October 8. The deadline is 48 hours away or less, so the plan is built backwards from a submission by 18:00 IST on October 10, with buffer.

**Block A: Thursday Oct 8, evening (about 5 to 6 hours): working skeleton**

- Create the repo, LICENSE, `.env.example`, virtual environment, SerpApi account and key.
- Run each engine once in the playground; save raw JSON to `fixtures/`. Confirm parameter names and the Indian ticker format.
- Build `ingest.py`: URL parse, metadata, transcript, language detection, normalisation.
- Build `extract.py` and test it on two transcripts. Done when you can print a list of claims with timestamps.
- Build the SQLite cache and `llm.py` interface.

**Block B: Friday Oct 9, full day: the product**

- Morning: `retrieve.py` with routing, tiering and caching; query drafting prompt; evidence for finance and health claims end to end.
- Midday: `judge.py` with the validator and the hard rules; verdicts for the two test videos. Then the numeric checker if time allows.
- Afternoon: FastAPI routes, event streaming, and the scorecard UI with timestamp links, evidence expanders and verdict filters.
- Evening: label the gold set of 5 videos and run the evaluation. Fix the worst prompt failures, not everything.
- Feature freeze at the end of Friday except bug fixes.

**Block C: Saturday Oct 10: polish and submit**

- Morning: README (problem, screenshots, setup, architecture diagram, accuracy results, limitations), cleanup, and a fresh-clone test on a clean machine or folder to confirm the setup steps work.
- By 13:00: record the demo (section 17) after a dry run. Upload as unlisted, and open the link in a private window.
- By 15:00: fill in the submission form: description, track, participant details, disclosures (project is new if you built it for this; list the AI tools used), accept Rules and Terms.
- By 18:00: submit. Keep the remaining hours as a buffer for upload or dashboard problems, not for new features.

**Cut order if you fall behind:** P2 features, then the timeline bar, then the numeric checker, then export. Never cut caching, the validator, the disclaimer or the README.

## 17. Demo Script (under 3 minutes)

Use a dry-run first; keep it at about 2:40 so you stay under the limit.

- **0:00 to 0:20, the problem:** “People act on money and health advice from videos nobody checks. This tool audits a video's claims against live search data.”
- **0:20 to 0:40, the input:** paste a pre-chosen video link and click Audit. Show the progress stream: transcript, claims, searching Scholar, News and Finance.
- **0:40 to 2:10, the scorecard:** show the summary counts and the timeline bar. Open three cards: one Contradicted or Mixed finance claim with its news or finance evidence; one health claim with a Scholar result; one prediction flagged Unverifiable with risk language. Click a timestamp to jump to the moment in the video.
- **2:10 to 2:35, how SerpApi is used:** show a diagram or the progress log naming the engines. State that every verdict is built only from retrieved evidence and that missing evidence is reported as such.
- **2:35 to 2:50, close:** mention the disclaimer, the gold-set accuracy figures and the repo link.

Run it live and locally as required; use demo mode only as a backup and say so if you do.

## 18. Draft Submission Description

**Finfluencer & Health-Claim Auditor** lets anyone paste a YouTube link and see which claims in the video are supported, contradicted, mixed, unsupported or unverifiable. It pulls the timestamped transcript, uses an LLM to extract specific checkable financial and health claims (including Hinglish videos), then retrieves live evidence through SerpApi: Google News for recent reporting, Google Scholar for research, Google Finance for market data, and Google Search for regulator and health-body pages. Verdicts are produced only from retrieved sources, with citations, confidence levels and timestamp links back to the video. Predictions and guarantees are flagged as unverifiable high-risk language rather than judged. It helps retail investors, families sharing health videos, and journalists make a quick, sourced first check. Search data is the core of the product: without live retrieval there is nothing to judge.

## 19. Mapping to Judging Criteria

- **Idea strength:** a clear insight: video is where misinformation spreads and where no checker exists; strong Indian relevance.
- **Originality:** audits video with timestamped evidence; thoughtful recombination of transcript, news, research and market data; honest handling of predictions and missing evidence.
- **Technical complexity:** multilingual transcript normalisation, structured claim extraction, domain routing, evidence tiering, a validated verdict engine, a deterministic numeric checker, caching, concurrency and live streaming.
- **Usefulness:** a ready-to-use scorecard for investors, families and journalists, with exports and timestamp links.
- **Meaningful SerpApi usage:** five engines used for distinct purposes, all essential to the verdicts; the README documents the search budget and engine mapping.

## 20. Open Questions to Settle Today

- Confirm the submission deadline (Oct 5 vs Oct 10) on the dashboard or with the organiser.
- Confirm Open Innovation vs Knowledge & Public Interest, and whether the Rules text leaves any doubt about the fit.
- Choose the LLM provider and confirm you have API access and quota for it.
- Choose five gold-set videos and the demo video, keeping the fairness guidance in section 15 in mind.
- Decide solo or team, and split work (ingest and extraction; retrieval and judging; UI and README) if there are teammates.

## 21. Team Prompts for Three People

**How to use:** every person opens their own AI coding assistant session and pastes (1) the **Shared Context** in 21.1, then (2) **their own prompt** (21.2, 21.3 or 21.4). Keep one long-running conversation per person so the assistant remembers the contract. List the AI tools you used in the submission disclosures.

Two rules every prompt repeats, because they prevent the most common failures: the assistant must never guess SerpApi parameter names (verify in the playground and docs), and nobody changes the shared schemas without telling the other two.

### 21.1 Shared Context (everyone pastes this first)

```
PROJECT
We are three people building 'Finfluencer & Health-Claim Auditor' for the SerpApi India Hackathon 2026 (Open Innovation track). Confirm the deadline on the dashboard; we plan for submission by 18:00 IST on Oct 10, 2026.

PRODUCT
The user pastes a YouTube link. We fetch the timestamped transcript, extract specific checkable claims (finance and health), retrieve live evidence through SerpApi (YouTube Video, YouTube Video Transcript, Google News, Google Scholar, Google Finance, Google Search), judge each claim using ONLY the retrieved evidence, and show a scorecard: every claim with its timestamp link, verdict, rationale and sources.

VERDICT LABELS: supported, contradicted, mixed, no_evidence, unverifiable (predictions, guarantees, testimonials, opinions).

NON-NEGOTIABLE RULES
- Verdicts come only from evidence retrieved for that claim. 'no_evidence' is a valid, first-class outcome. Never invent sources.
- We judge claims, never people. No creator score, no 'fraud' wording. Show counts, not grades.
- Always show a disclaimer: not financial or medical advice.
- Free SerpApi plan is 250 searches per month. EVERY SerpApi call must go through app/serp.py (cache, retries, DEMO_MODE). Budget: about 26 calls per video, max 8 claims, max 3 searches per claim.
- Never guess SerpApi engine names, parameters or response fields. Check the official docs / playground, save a real response as a fixture, then code against it. If unsure, isolate the call in one small function marked TODO-VERIFY.
- Never commit API keys. Use .env and .env.example.
- Only use code and content we are allowed to use; the project has an MIT LICENSE.

STACK
Python 3.11+, FastAPI, SQLite, official 'serpapi' Python library, plain HTML/CSS/JS frontend served by FastAPI (React only if Person C insists and can finish), LLM behind a small interface in app/llm.py (provider chosen by the team; keep it swappable).

REPO LAYOUT
finfluencer-auditor/
  README.md, LICENSE, .env.example, requirements.txt
  app/ main.py, pipeline.py, serp.py, db.py, llm.py, schemas.py, ingest.py, extract.py, retrieve.py, judge.py, numeric.py, config/source_tiers.yaml
  web/ index.html, app.js, styles.css
  fixtures/ serp_cache.json, sample_audit.json
  eval/ gold/, run_eval.py
  scripts/ dump_cache.py
  tests/

OWNERSHIP
- Person A: serp.py, db.py, llm.py, ingest.py, extract.py, pipeline.py, main.py (API and streaming).
- Person B: retrieve.py, judge.py, numeric.py, source_tiers.yaml, fixtures, eval, scripts/dump_cache.py.
- Person C: web/, README, LICENSE, demo, submission form. Also owns fixtures/sample_audit.json.
- schemas.py is shared. Any change must be announced in the team chat and made by one person in a small PR.

CALL INTERFACES (do not change signatures without agreement)
- serp.call(engine: str, **params) -> dict          (A) cached, retried, DEMO_MODE-aware
- llm.complete_json(system: str, user: str) -> dict (A) returns parsed JSON or raises
- ingest.get_video(url: str) -> VideoData           (A)
- extract.extract_claims(video: VideoData) -> list[Claim]   (A)
- retrieve.gather_evidence(claim: Claim, video: VideoData) -> list[Evidence]   (B)
- numeric.check(claim: Claim, evidence: list[Evidence]) -> Optional[NumericCheck]   (B)
- judge.judge_claim(claim: Claim, evidence: list[Evidence], video: VideoData) -> Verdict   (B)
- pipeline.run_audit(url: str, audit_id: str, emit) -> Audit   (A) emit(ProgressEvent)

API (Person A builds, Person C consumes)
- POST /api/audits {url} -> {id}
- GET /api/audits/{id}/events -> Server-Sent Events of ProgressEvent JSON
- GET /api/audits/{id} -> Audit JSON (segments omitted)
- GET /api/audits/{id}/export?format=md|json
- GET /api/health
```

**The shared data contract** (save as `app/schemas.py`; Person C builds the mock JSON from it):

```python
from typing import Literal, Optional
from pydantic import BaseModel

Domain = Literal['finance', 'health', 'other']
ClaimType = Literal['verifiable_fact', 'prediction', 'advice', 'testimonial', 'opinion']
VerdictLabel = Literal['supported', 'contradicted', 'mixed', 'no_evidence', 'unverifiable']

class Segment(BaseModel):
    start: float
    text: str            # English-normalised
    text_original: str   # as in the transcript

class VideoData(BaseModel):
    video_id: str
    url: str
    title: str
    channel: str
    published_at: Optional[str] = None
    description: str = ''
    language: str        # 'en', 'hi', 'hi-en'
    segments: list[Segment] = []

class Entities(BaseModel):
    companies: list[str] = []
    tickers: list[str] = []
    ingredients: list[str] = []
    conditions: list[str] = []
    regulators: list[str] = []

class Claim(BaseModel):
    id: str
    start_seconds: int
    end_seconds: Optional[int] = None
    quote_original: str
    claim_english: str
    domain: Domain
    claim_type: ClaimType
    checkable: bool
    entities: Entities
    risk_flags: list[str] = []
    priority: int        # 1 = highest

class Evidence(BaseModel):
    id: str              # 'e1', 'e2' ... unique within the claim
    claim_id: str
    engine: str          # e.g. 'google_news'
    title: str
    source: str
    tier: Literal[1, 2, 3]
    date: Optional[str] = None
    snippet: str
    url: str

class NumericCheck(BaseModel):
    field: str
    claimed: float
    actual: float
    within_tolerance: bool

class Verdict(BaseModel):
    claim_id: str
    label: VerdictLabel
    confidence: Literal['low', 'medium', 'high']
    rationale: str
    evidence_ids: list[str]
    numeric_check: Optional[NumericCheck] = None

class ClaimResult(BaseModel):
    claim: Claim
    evidence: list[Evidence]
    verdict: Optional[Verdict] = None
    error: Optional[str] = None

class Summary(BaseModel):
    counts: dict[str, int]       # keyed by VerdictLabel
    risk_flag_count: int
    claims_total: int

class Audit(BaseModel):
    id: str
    status: Literal['queued', 'running', 'done', 'failed']
    video: Optional[VideoData] = None
    results: list[ClaimResult] = []
    summary: Summary
    error: Optional[str] = None

class ProgressEvent(BaseModel):
    stage: Literal['ingest', 'extract', 'retrieve', 'judge', 'done', 'error']
    message: str
    progress: float      # 0.0 to 1.0
    claim_id: Optional[str] = None
```

### 21.2 Prompt for Person A: Pipeline and Backend (the spine)

```
ROLE
You are my senior Python backend engineer, pair-programming with me. I am Person A on a 3-person hackathon team. I own the spine of the product: the SerpApi client wrapper, ingestion, claim extraction, orchestration, the database and the API. I have pasted the Shared Context and app/schemas.py above. Follow them exactly. If you think a schema field is missing, propose the change and wait for my approval.

WORKING STYLE
- Build in the order below. After each step, give me a short test I can run, then wait for me to confirm before the next step.
- Never guess SerpApi engine names or parameters. Ask me to check the playground/docs, or isolate the call and mark it TODO-VERIFY.
- Keep code simple and readable. Type hints everywhere. No unnecessary frameworks.

BUILD ORDER

1. app/serp.py - the single door to SerpApi.
   - call(engine, **params) -> dict using the official serpapi library and SERPAPI_API_KEY from .env.
   - Cache in SQLite (table api_cache) keyed by sha256 of engine + sorted params. Return cached responses without spending credits.
   - Timeout, 3 retries with exponential backoff on transient errors; clear exception types (SerpApiError, RateLimited).
   - DEMO_MODE=1: read only from the cache (and from fixtures/serp_cache.json at startup); on a cache miss raise a clear error. Never hit the network in demo mode.
   - Keep a counter of live calls made this process and log it, so we can watch our 250-call budget.

2. app/db.py and app/llm.py.
   - db.py: SQLite helpers for tables audits, claims, evidence, verdicts, api_cache. Store results as JSON blobs matching schemas.py to save time.
   - llm.py: complete_json(system, user) -> dict. One provider implementation chosen by me (ask me which), reading its key from .env. Temperature low. Strip code fences, parse JSON, retry once on malformed JSON, then raise. Cache LLM outputs by hash of (system, user) so reruns are free.

3. app/ingest.py - get_video(url) -> VideoData.
   - Parse watch, youtu.be, shorts and embed URLs to a video_id; reject bad input with a friendly error.
   - Fetch metadata (title, channel, description, publish date) with the YouTube Video engine and the timestamped transcript with the YouTube Video Transcript engine, both through serp.call. Verify engine names and parameters first.
   - If no transcript exists, raise TranscriptUnavailable with a human message ('This video has no captions we can read.').
   - Detect language (use the transcript language field if present; otherwise a cheap heuristic or one LLM call). If not English, normalise to English in batches of about 40 segments, keeping the same number of segments in the same order. Validate the count; if it does not match, fall back to the original text for that batch. Always keep text_original.

4. app/extract.py - extract_claims(video) -> list[Claim].
   - Windows of 150 seconds with 20 seconds overlap, each keeping its segment timestamps.
   - Call the LLM per window using the prompt below. Validate output with schemas.Claim; drop invalid items.
   - start_seconds must come from the segment where the claim begins (round to int).
   - De-duplicate across windows using difflib similarity > 0.8 on claim_english; keep the earliest.
   - Risk-language detector (regex, case-insensitive) over quote_original and claim_english, in English and common Hinglish: guaranteed, guarantee, risk free, no risk, double your money, 2x, 10x, multibagger, sure shot, 100%, cure, cures, reverse diabetes, no side effects, doctors hide, pakka, paisa double. Put matches in risk_flags (list of matched phrases).
   - Rank: checkable verifiable_fact claims with named entities first, then risk-flagged claims, then the rest. Assign priority 1..n and keep the top 8 checkable claims plus up to 4 non-checkable (prediction/testimonial) claims for display as 'unverifiable'.
   - Unit-test the risk detector, the dedupe and the window splitter without calling any API.

EXTRACTION SYSTEM PROMPT (use as is, then improve with examples from real transcripts):
  You extract checkable claims from a YouTube transcript window about money or health. Return JSON only: {'claims': [ ... ]}.
  Each claim object: quote_original (exact words, same language as the transcript), claim_english (one clear sentence in English, same meaning, never stronger or softer), start_seconds (the timestamp of the segment where it begins), domain ('finance' | 'health' | 'other'), claim_type ('verifiable_fact' | 'prediction' | 'advice' | 'testimonial' | 'opinion'), checkable (true only for verifiable facts about the world: company numbers, regulator actions, scientific or medical effects), entities {companies, tickers, ingredients, conditions, regulators}.
  Rules: extract only statements a viewer might act on. One claim per object. Ignore greetings, ads, sponsor reads and filler. Predictions and guarantees (e.g. 'this stock will double') are claim_type 'prediction' and checkable false. Personal stories are 'testimonial'. Never add facts that are not in the transcript. If the window has no claims return {'claims': []}.

5. app/pipeline.py - run_audit(url, audit_id, emit) -> Audit.
   - Stages: ingest -> extract -> for each checkable claim (concurrency 4 using a thread pool): retrieve.gather_evidence -> numeric.check (if domain is finance) -> judge.judge_claim.
   - Non-checkable claims skip retrieval and get a Verdict with label 'unverifiable' and a fixed rationale ('Predictions, guarantees and personal testimonials cannot be fact-checked.').
   - Emit ProgressEvent at every stage and after every claim, with a sensible 0.0-1.0 progress value.
   - Wrap each claim in try/except: a failure sets ClaimResult.error and the pipeline continues. Whole-audit failures set status 'failed' with a friendly error.
   - Compute Summary (counts per label, risk_flag_count, claims_total). Persist everything.
   - Until Person B's modules exist, use stubs that return fake Evidence and Verdicts so the pipeline and UI can be tested end to end.

6. app/main.py - FastAPI.
   - Routes exactly as listed in the Shared Context. Run the audit in a background task; GET /api/audits/{id}/events streams ProgressEvent as Server-Sent Events (also send a final 'done' event); GET /api/audits/{id} returns the Audit without segments.
   - Export: markdown (title, summary counts, then each claim with timestamp link, verdict, rationale, source links) and JSON.
   - Serve the web/ folder as static files. CORS open for local dev. /api/health returns demo-mode status and live-call count.

ACCEPTANCE CHECKS (I will verify these)
- A real 10-minute video produces a list of claims with correct timestamps in under 30 seconds (before retrieval).
- Running the same URL twice makes zero extra SerpApi calls and zero extra LLM calls.
- DEMO_MODE=1 runs end to end offline from cached data.
- A video without captions returns a friendly error, not a stack trace.
- Total SerpApi calls for one video, including B's retrieval, stay near 26.

DO NOT
- Do not call SerpApi anywhere except through serp.py.
- Do not put API keys in code, logs or the repo.
- Do not add features outside this list. If I am behind schedule, drop in this order: export, windows overlap tuning, Hinglish batching optimisations. Never drop caching.

START
Confirm you understood, list the SerpApi details you need me to verify, and begin with step 1.
```

### 21.3 Prompt for Person B: Evidence and Verdicts (the brain)

```
ROLE
You are my senior Python engineer and applied-LLM specialist, pair-programming with me. I am Person B on a 3-person hackathon team. I own evidence retrieval, the verdict engine, the finance numeric checker, the source-tier config, the offline fixtures and the accuracy evaluation. I have pasted the Shared Context and app/schemas.py above. Follow them exactly. If a schema field is missing, propose the change and wait.

WORKING STYLE
- Build in the order below; after each step give me a short test and wait for my confirmation.
- Never guess SerpApi engine names, parameters or response fields. I will run each engine once in the SerpApi playground and paste the raw JSON to you; write the parsers against that real JSON and save it as a fixture. If unsure, mark TODO-VERIFY.
- Every SerpApi call goes through serp.call(engine, **params) (Person A owns it). Until it exists, code against that signature with a tiny local stub.

BUILD ORDER

1. Fixtures first (before any logic).
   - Together with me, run once in the playground: Google News, Google Scholar, Google Finance (one Indian ticker, e.g. a large NSE stock), and Google Search. Save the raw JSON under fixtures/raw/.
   - Write scripts/dump_cache.py to export the SQLite api_cache into fixtures/serp_cache.json (so DEMO_MODE and tests run offline) and a loader note in the README.

2. app/config/source_tiers.yaml.
   - Tier 1: regulators, government and health bodies, peer-reviewed publishers, exchanges. Examples to start: sebi.gov.in, rbi.org.in, nseindia.com, bseindia.com, mca.gov.in, india.gov.in, nic.in, icmr.gov.in, mohfw.gov.in, fssai.gov.in, who.int, nih.gov, ncbi.nlm.nih.gov, cdc.gov, nature.com, thelancet.com, bmj.com, jamanetwork.com, sciencedirect.com, springer.com, wiley.com.
   - Tier 2: established news organisations (start with a short list of well-known national and international outlets; I will review it).
   - Tier 3: everything else (blogs, forums, social, unknown).
   - Write a function tier_for(url_or_domain) -> 1|2|3 that matches by domain suffix. Unit-test it.

3. app/retrieve.py - gather_evidence(claim, video) -> list[Evidence].
   - Router by claim.domain:
       finance -> Google Finance (only when a ticker or a well-known listed company is identified), Google News, Google Search aimed at regulator pages (query includes the regulator or entity name).
       health  -> Google Scholar, Google News, Google Search aimed at health-body pages (query includes the ingredient/condition plus an authority name).
       other   -> Google News and Google Search.
   - Query drafting: one LLM call (llm.complete_json) per claim returning up to 3 short queries total (entity-specific, no filler words, include the video's publish year when the claim is time-bound). Hard cap: 3 SerpApi calls per claim.
   - Parse each engine's real response into Evidence: id 'e1', 'e2'... within the claim, claim_id, engine, title, source (publisher or domain), tier (from tier_for), date if present, snippet, url.
   - Scholar: use year and citation count to rank; keep the publisher/venue in the snippet when available.
   - De-duplicate by URL, rank by tier then relevance then recency, keep the top 5 per claim. Return an empty list (not an error) when nothing relevant is found.
   - Query-drafting system prompt (use as is, then improve): 'You write web search queries to check one claim. Return JSON only: {'queries': [{'engine': 'google_news' | 'google_scholar' | 'google_finance' | 'google', 'q': '...'}]}. Max 3 queries. Use specific entity names. For health claims include the ingredient, the condition and words like clinical trial or systematic review. For finance claims include the company name, ticker if known, and the specific fact (for example debt, results, regulator order). Never include opinions or filler. Prefer the engines that suit the domain.'

4. app/judge.py - judge_claim(claim, evidence, video) -> Verdict.
   - If evidence is empty: return label 'no_evidence', confidence 'low', rationale 'No relevant sources were found for this claim.' without calling the LLM.
   - Otherwise one LLM call with the claim, the video's publish date, and a numbered evidence list (id, tier, source, date, title, snippet).
   - Verdict system prompt (use as is, then add 2-3 few-shot examples including a no_evidence case): 'You judge ONE claim using ONLY the evidence provided. Return JSON only: {'label': 'supported' | 'contradicted' | 'mixed' | 'no_evidence', 'confidence': 'low' | 'medium' | 'high', 'rationale': '...', 'evidence_ids': ['e1']}. Rules: use only the provided evidence; if it does not address the claim, answer no_evidence; prefer higher-tier sources (1 is best); if credible sources disagree or only partly support the claim (for example animal studies only, or true for a different period), answer mixed; judge relative to the video's publish date; rationale is at most 3 sentences, neutral, about the claim and never about the person; cite only ids that exist.'
   - Code-level validator (this is the product's safety net, test it hard):
       * drop any evidence_id not in the provided list;
       * if no valid evidence_ids remain, force label 'no_evidence' and confidence 'low';
       * 'supported' or 'contradicted' require at least one cited evidence item of tier 1 or 2; otherwise downgrade to 'mixed' with confidence 'low';
       * Tier-3-only evidence can never produce 'supported' or 'contradicted';
       * rationale longer than 3 sentences is truncated.
   - Never produce 'unverifiable' here; Person A's pipeline assigns it for non-checkable claims.

5. app/numeric.py - check(claim, evidence) -> Optional[NumericCheck] (P1).
   - Only for finance claims that state a number about a listed company (price, market cap, P/E, 52-week range, dividend yield) AND only for fields that the Finance engine response really contains (use the saved raw JSON to decide which).
   - Extract the claimed number with a small LLM call or regex, normalise units (crore, lakh, billion, %), compare with a sensible tolerance (for example 5%), and return NumericCheck. If the field is not available, return None and let News/Search handle it.
   - judge.py should receive the numeric result as an extra evidence-like line and treat a failed check as strong support for 'contradicted'.

6. eval/ - accuracy numbers for the README.
   - Gold format: eval/gold/<video_id>.json with the checkable claims a human marked (start_seconds, short claim text) and the human verdict label for each.
   - run_eval.py: runs the pipeline in DEMO_MODE on the gold videos and prints (a) extraction recall: share of human-marked claims matched by an extracted claim within 20 seconds and with similar text, (b) verdict agreement on matched claims, (c) share of verdicts with at least one valid evidence id, (d) average live SerpApi calls per video.
   - Save results to eval/results.md in plain, honest numbers, including failures.

ACCEPTANCE CHECKS (I will verify these)
- Given a finance claim and a health claim from the fixtures, gather_evidence returns up to 5 de-duplicated Evidence items with correct tiers, using at most 3 calls per claim.
- A claim with no relevant results gives no_evidence without an LLM call.
- Feeding the judge a made-up evidence_id never survives validation.
- Tier-3-only evidence never yields 'supported' or 'contradicted'.
- Everything in tests/ passes offline in DEMO_MODE.

DO NOT
- Do not let the LLM cite or invent sources outside the evidence list.
- Do not write rationales about the creator's character or intent.
- Do not exceed 3 SerpApi calls per claim or 8 checkable claims per video.
- Do not tune prompts on the gold set and then report that same score as unbiased; keep 1-2 videos as a held-out test.
- If we run behind, drop in this order: numeric.py, Scholar ranking refinements, eval extras. Never drop the validator.

START
Confirm you understood, tell me exactly which playground responses you need me to paste, and begin with step 1.
```

### 21.4 Prompt for Person C: Frontend, Product and Submission (the face)

```
ROLE
You are my senior frontend engineer and product designer, pair-programming with me. I am Person C on a 3-person hackathon team. I own the web UI, the README, the demo and the final submission. I have pasted the Shared Context and app/schemas.py above. The UI must consume exactly the Audit JSON defined there. If a field is missing, propose the change and wait.

WORKING STYLE
- Build against a mock first. Do not wait for the backend.
- Plain HTML, CSS and JavaScript in web/ (served by FastAPI). No build step unless I explicitly choose React. Keep it fast to load and easy to run with one command.
- Build in the order below; after each step give me a way to see it in the browser, and wait for my confirmation.

BUILD ORDER

1. fixtures/sample_audit.json.
   - Write a realistic mock Audit (one finance-heavy video and one health-heavy video are ideal; start with one) with about 8 claims covering ALL verdict labels, at least two risk_flags examples, evidence items at tiers 1, 2 and 3, one claim with error set, and one no_evidence claim. Valid against schemas.py. Also create a second mock in status 'running' with partial results for testing the live view.
   - The Audit JSON the UI reads has no transcript segments.

2. web/index.html + styles.css + app.js - the single page.
   - Header with product name and a short one-line promise.
   - A persistent disclaimer banner: results are based on sources found at the time of the audit; this is not financial or medical advice; verdicts are about claims, not people.
   - Input: a YouTube URL field with validation and an Audit button. Example links for quick testing (I will supply them).
   - Progress panel: shows the current stage and a progress bar, fed by Server-Sent Events from GET /api/audits/{id}/events (use EventSource; fall back to polling GET /api/audits/{id} every 2 seconds if SSE fails). Add a dev switch (?mock=1) that replays sample_audit.json with fake progress events.
   - Summary header: video title and channel, total claims, one counter per verdict label, and a risk-language count. Never show a single trust score or grade for the creator.
   - Timeline bar (P1): a horizontal bar representing the video length, with a marker per claim at its timestamp, coloured by verdict; clicking a marker scrolls to that claim card. Needs the video duration; if it is not available, use the last claim's timestamp.
   - Filter chips by verdict label and by domain (finance / health), plus a sort by timestamp or by priority.
   - Claim card: clickable timestamp (link format https://youtu.be/<video_id>?t=<seconds>, opens in a new tab), quoted line in the original language, English version, domain badge, verdict badge, confidence, rationale, risk-flag chips, and an expandable evidence list (source name, tier label, date, snippet, external link). If a numeric_check exists, show claimed vs actual in a small line. Show 'could not check' with the error for failed claims.
   - Verdict styling: each label has a colour AND an icon AND text (never colour alone, for accessibility). Suggested: supported = green check, contradicted = red cross, mixed = amber half-circle, no_evidence = grey question mark, unverifiable = purple warning triangle.
   - Export buttons that call GET /api/audits/{id}/export?format=md and ?format=json.
   - Error states with friendly messages: invalid link, no captions, server error, no claims found.
   - Responsive down to a phone width; keyboard-focusable controls; sensible contrast; dark and light friendly.

3. Optional (only after everything else works): embed the YouTube player in a side panel and use the IFrame API to seek to a claim's timestamp when its card is clicked.

4. Connect to the real backend as soon as Person A's routes exist; switch the base URL from the mock to /api and fix any contract mismatches by talking to A and B, not by changing the UI silently.

5. README.md (this is judged). Sections: what it does and why; screenshots or a GIF of the scorecard; architecture diagram of the pipeline (a simple image or Mermaid); how each SerpApi engine is used and why (a short table); setup in 6 steps or fewer (clone, create venv, install, copy .env.example to .env and add keys, run, open browser) plus DEMO_MODE instructions; the verdict labels and the hard rules (evidence-only judging, no_evidence is valid, predictions are unverifiable); accuracy results copied honestly from eval/results.md; limitations and responsible-use notes; team and AI-tools disclosure; license. Test the setup steps from a fresh clone, ideally by a teammate who did not write them.

6. Demo video (under 3 minutes) and submission.
   - Write the script from section 17 of the PRD and rehearse once. Use a safe demo video (our own recording, a consenting creator, or clearly educational content). Record the project running locally, with the live progress panel visible. Upload as public or unlisted and open the link in a private window to confirm it plays without a login.
   - Prepare the repo: public, LICENSE present, .env.example present, no keys committed (search the git history), README complete.
   - Fill in the submission form: project name; one track (Open Innovation); description (use the draft in section 18 of the PRD: what it does, who it helps, how it uses SerpApi); repo link; demo link; lead participant details (name, email, phone, occupation, years of experience) and teammates' names and emails; disclosures (whether the project existed before: no, built for this hackathon, unless true; list the AI tools used); accept the Rules and Terms. Save a draft early, review it with A and B, then press Submit well before the deadline.

ACCEPTANCE CHECKS (I will verify these)
- Opening index.html with ?mock=1 shows a full scorecard with every verdict label, filters working, timestamp links correct.
- The UI never shows a creator-level score, and the disclaimer is always visible.
- With the real backend, a live run shows streaming progress and renders the same scorecard.
- A fresh-clone setup works by following only the README.
- The demo video is under 3 minutes, plays in a private window, and shows the product running locally.

DO NOT
- Do not hard-code demo data into the final UI path; mock mode must be opt-in.
- Do not add a login, database or framework that the product does not need.
- Do not use language like 'fake', 'fraud' or 'liar'; use the verdict labels only.
- If we run behind, drop in this order: embedded player, timeline bar, sort options, export. Never drop the disclaimer, the evidence expanders or the README.

START
Confirm you understood, ask me anything you need about design preferences, and begin with step 1.
```

### 21.5 Handoffs and Integration Checkpoints

- **Hour 1 (all three):** agree and commit `app/schemas.py`; C commits `fixtures/sample_audit.json`; A commits the repo skeleton with stub modules so B and C can import them.
- **Thursday night:** A shows a transcript and a claims list on a real video; B shows evidence for one finance and one health claim from saved fixtures; C shows the mock scorecard.
- **Friday around 1 pm:** first end-to-end run. Fix contract mismatches together; nobody works around them silently.
- **Friday evening:** feature freeze. Each person labels about two gold-set videos for B's evaluation. B reports honest numbers.
- **Saturday morning:** fresh-clone test by a teammate who did not write the README; fix everything they hit.
- **Saturday 1 pm:** demo recorded. **3 pm:** form filled in and reviewed by all three. **6 pm:** submitted.

**Pull request rules:** small PRs, merged to `main` within a few hours, and never edit another person's module without telling them. Anything touching `schemas.py` needs a message in the team chat first.
