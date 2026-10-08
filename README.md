# Finfluencer & Health-Claim Auditor

FastAPI + SQLite backend that turns a public YouTube URL into a timestamped claim scorecard. It is evidence-first: missing retrieval is shown as **No evidence found**, while predictions and opinions are **Unverifiable**. It never scores creators.

## Setup

Python 3.11+ is required. Create a virtual environment, install `requirements.txt`, copy `.env.example` to `.env`, and set `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, and `GEMINI_MODEL=gemini-3.5-flash`. This project uses the currently serviceable Gemini model for this account; the model remains configurable. Configure a SerpApi key for live retrieval.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Health: `GET http://127.0.0.1:8000/api/health`. Submit with `POST /api/audits` and JSON `{"url":"https://youtu.be/..."}`; consume `/events` and then the scorecard endpoint. Export with `?format=md` or `?format=json`.

`DEMO_MODE=1` disables live SerpApi calls and only serves responses already in the local SQLite cache; it does not fabricate fixtures. `SERPAPI_API_KEY` is never logged or returned. All SerpApi requests are centralized in `app/serp.py` and cached by deterministic engine/parameter keys.

Language handling is transcript-dependent: English is supported; Hindi and mixed Hindi-English/Hinglish are supported and covered by local tests; other languages are handled generically when YouTube/SerpApi supplies usable timestamped transcript text. Original transcript wording and timestamps are retained. Gemini structured JSON outputs normalize non-English claims into faithful English. If Gemini is unavailable or returns invalid structured data, extraction fails conservatively rather than inventing claims or copying source-language text as an English normalization.

Claim extraction uses timestamp-aware overlapping windows, asks the configured LLM for complete propositions rather than fragments, retains original and normalized text, classifies finance/health/other and fact/prediction/opinion/advice/statistic types, extracts entities and numeric expressions, and caps the final shortlist at eight claims. The extraction layer does not produce evidence or verdicts.

Person B interfaces are in `app/retrieve.py`, `app/judge.py`, and `app/numeric.py`. Their current explicit `not_implemented` state is safe and does not claim real evidence or verdicts. Source tier configuration is in `config/source_tiers.yaml`.

This is not financial or medical advice. Results reflect retrieved evidence at the time of an audit and can be incomplete or wrong; consult qualified professionals.

Run tests with `pytest -q`.
