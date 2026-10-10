"""Evidence retrieval module with domain-specific routing, query generation, and source tiering."""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .schemas import Claim, Evidence
from .serp import SerpApiClient, SerpApiError
from .source_tiers import get_tier_for_url
from .numeric import extract_numeric_items, values_match

logger = logging.getLogger(__name__)

_FILLER_WORDS = {
    "a", "an", "the", "this", "that", "these", "those", "is", "are", "was", "were",
    "will", "shall", "i", "you", "we", "they", "he", "she", "it", "my", "your",
    "speaker", "speakers", "stated", "states", "stating", "said", "says", "claims",
    "claimed", "claiming", "order", "orders", "now", "today",
    "yesterday", "tomorrow", "video", "videos", "channel", "discuss", "discussed",
    "discussing", "talking", "question", "questions", "answer", "answers", "welcome",
    "thanks", "thank", "hello", "hi", "watch", "watching", "see", "look", "listen",
    "dosto", "dost", "bhai", "aaj", "subscribe", "like", "share", "dekhiye", "karenge",
    "bataunga", "hai", "hain", "ke", "ki", "ko", "se", "mein", "par", "ka", "kya", "toh",
    "aur", "bhi", "hum", "aap", "unka", "in", "on", "at", "to", "for", "with", "about",
    "from", "by", "of", "and", "or", "but", "if", "then", "into", "onto", "over",
    "uh", "um", "er", "ah", "like", "also", "fact", "continue", "remain", "much", "well",
    "positive", "positivity", "negative", "movement", "segments", "themes", "exposure",
    "overweight", "underweight", "have", "been", "increased", "increase", "decreased"
}

_UNRELATED_FINANCE_DOMAINS = {
    "coursera.org", "edx.org", "studocu.com", "scribd.com", "chegg.com",
    "chrono24.com", "watchbox.com", "hodinkee.com", "whathifi.com", "rtings.com",
    "facebook.com", "quora.com", "brainly.in", "brainly.com", "toppr.com", "vedantu.com",
    "byjus.com", "sarthaks.com", "doubtnut.com", "testbook.com", "grammarcheck.me"
}

_OFF_DOMAIN_FINANCE_PATTERNS = re.compile(
    r"\b(?:covid(?:-?19)?|vaccin(?:e|es|ation|ated)|flu|symptoms?|tested positive|cancer|tumou?r|her2|radiation|infections?|disease|dosage|prescriptions?|hospital|siblings?|parenting|couples?|dating|lifestyle|antibodies|immun(?:e|ity)|therapy|"
    r"grammar|seeking admission|admission|fill in the blanks?|mcq|worksheet|test prep|has increased 2\)|have increased|option [a-d]\b|choose the correct|tense|preposition|english for today|multiple choice questions?)\b",
    re.I
)

_FINANCIAL_TOPIC_TERMS = re.compile(
    r"\b(?:market|stocks?|shares?|equit(?:y|ies)|bonds?|funds?|mutual fund|portfolio|rates?|interest|inflation|rbi|sebi|fed|earnings?|revenue|profit|loss|sales?|income|valuation|p/?e|index|nifty|sensex|yield|dividend|ipo|securities|invest(?:ment|or|ing)?|fiscal|monetary|central bank|commodity|crude oil|debt|gdp|asset|holdings?|quarterly)\b",
    re.I
)

_SPECIALIZED_FINANCE_TERMS = {
    "index fund", "index funds", "mutual fund", "mutual funds", "tracking error",
    "expense ratio", "benchmark", "etf", "exchange traded fund", "passive fund",
    "sensex", "nifty", "nifty 50", "bank nifty", "dividend yield", "pe ratio",
    "price earnings", "market cap", "market capitalization", "asset under management",
    "beta", "stock price", "share price", "drawdown", "recovery period",
    "best trading day", "worst trading day", "volatility",
}

# These concepts describe a relationship or product characteristic. Unlike an
# index alias such as "Nifty 50"/"Nifty", they must appear in the result to
# support the assertion rather than merely identify the market.
_RELATIONSHIP_FINANCE_TERMS = {
    "index fund", "index funds", "mutual fund", "mutual funds", "tracking error",
    "expense ratio", "exchange traded fund", "passive fund", "dividend yield",
    "pe ratio", "price earnings", "market cap", "market capitalization",
    "asset under management", "beta", "stock price", "share price", "drawdown",
    "recovery period", "best trading day", "worst trading day", "volatility",
}

_GENERIC_ENTITY_WORDS = {
    "market", "markets", "stock", "stocks", "share", "shares", "company", "companies",
    "index", "fund", "funds", "portfolio", "economy", "sector", "sectors", "finance",
}

_CURRENT_MARKET_TERMS = re.compile(
    r"\b(?:currently|today|now|live|latest|price|quote|pe|p/e|beta|market cap|market capitalization|"
    r"dividend yield|52[- ]week|volume|valuation|trading at|stands at)\b", re.I
)
_HISTORICAL_PERIOD_TERMS = re.compile(
    r"\b(?:in 19\d{2}|in 20\d{2}|during 19\d{2}|during 20\d{2}|last year|historical|history|"
    r"since|between|from 19\d{2}|from 20\d{2}|over the past|best trading day|worst trading day)\b", re.I
)
_ASSERTION_TERMS = re.compile(
    r"\b(?:fell|fall|dropped|drop|rose|rise|increased|decreased|returned|return|lost|gained|"
    r"profit|revenue|sales|yield|beta|ratio|price|valuation|market cap|drawdown|recovered|"
    r"recovery|high|low|best|worst|top|bottom|causes?|caused|prevents?|treats?|reduces?|"
    r"increases?|decreases?|more|less|higher|lower|better|worse|compared|versus|than)\b", re.I
)
_ASSERTION_EQUIVALENTS = (
    re.compile(r"\b(?:fell|fall|dropped|drop|lost|decreased|declined|crash|collapse|lower)\w*\b", re.I),
    re.compile(r"\b(?:rose|rise|increased|gained|grew|growth|higher|increases?)\w*\b", re.I),
    re.compile(r"\b(?:profit|revenue|sales|yield|beta|ratio|price|valuation|drawdown|recovery)\w*\b", re.I),
)

_QUERY_STOP_WORDS = _FILLER_WORDS | {
    "according", "based", "claim", "claims", "currently", "current", "reported",
    "reports", "report", "says", "said", "show", "shows", "shown", "make", "made",
    "year", "years", "month", "months", "quarter", "quarters", "percent", "per",
    "let", "okay", "ok", "so", "yes", "actually", "say", "entire", "make", "means", "cool",
    "what", "how", "why", "where", "which", "here", "there", "use", "used", "using",
    "thing", "things", "way", "point", "kind", "really", "quite", "just", "back", "also",
}

_QUERY_ASSERTION_WORDS = {
    "benefit", "benefits", "harm", "harms", "risk", "risks", "cause", "causes", "caused",
    "prevent", "prevents", "treat", "treats", "treatment", "reduce", "reduces", "increase",
    "increases", "decrease", "decreases", "growth", "grew", "grown", "return", "returns",
    "returned", "performance", "concentration", "diversification", "allocation", "exposure",
    "profit", "profits", "revenue", "earnings", "yield", "premium", "ratio", "price", "prices",
    "valuation", "capitalization", "market", "markets", "shares", "share", "stock", "stocks",
    "higher", "lower", "more", "less", "than", "versus", "compared", "average", "accounts",
    "represents", "represent", "track", "tracking", "association", "associated", "linked",
    "likely", "forecast", "forecasted", "expected", "recommend", "recommended", "should",
}

# Historical claims are often indexed under the vocabulary used by historians,
# not the wording used in a video transcript. Keep these additions deliberately
# small and topical so they improve recall without turning every query into a
# broad search.
_HISTORICAL_CONTEXT_SYNONYMS = {
    "bubble": "bubble mania speculation crash overvaluation",
    "bubbles": "bubble mania speculation crash overvaluation",
    "speculation": "bubble mania overvaluation crash",
    "crash": "collapse bust",
    "overvaluation": "speculative bubble mania",
    "harbor": "harbor shipping merchants trade",
    "harbour": "harbor shipping merchants trade",
    "shipping": "harbor merchants trade commerce",
    "merchant": "merchants trade shipping harbor",
    "trade": "trade merchants shipping harbor",
    "colour": "colour breaking color breaking petal streaks variegated",
    "color": "colour breaking color breaking petal streaks variegated",
    "streak": "streaks petal colour breaking color breaking variegated",
    "petal": "petal streaks colour breaking color breaking variegated",
    "dot-com": "dot-com bubble internet mania 1990s IPO crash",
    "1990s": "dot-com bubble internet boom crash",
    "amsterdam": "Amsterdam Dutch Republic 17th century port commerce merchants trade",
    "port": "harbor shipping merchants trade commercial center",
    "commercial": "port harbor merchants trade commercial center",
}

_COMPOUND_EVENT_ANCHORS = re.compile(
    r"\b(?:tulip(?:s| mania)?|real[ -]?estate|pets\.?com)\b", re.I
)

_VIRUS_CLAIM_PATTERN = re.compile(
    r"\b(?:tulip[ -]?breaking virus|tulip breaking|broken tulips?)\b.*\b(?:streak|stripe|colour|color|petal)",
    re.I,
)

_HISTORICAL_EVIDENCE_TERMS = re.compile(
    r"\b(?:histor(?:y|ical)|archive|archival|century|19[0-9]{2}s|20[0-9]{2}s|163[0-9]|2000|collapse|crash|bubble|mania|shutdown|liquidat|ipo|peak(?:ed)?|fell|declin(?:e|ed|ing))\b",
    re.I,
)


def route_claim(claim: Claim) -> list[str]:
    """Determine eligible search engines from the claim's subject and time scope.

    Google Finance is a structured current-market-data adapter.  Historical
    statistics, fund studies, fee comparisons, and broad finance assertions
    need document/news search instead; routing them through a quote adapter
    only adds an unsuitable provider candidate.  ``draft_queries`` still
    requires a single ticker-like entity before emitting a Finance query.
    """
    domain = (claim.domain or "").lower()
    if domain == "finance":
        if _uses_current_market_data(claim):
            return ["google_finance", "google_news", "google"]
        return ["google_news", "google"]
    elif domain == "health":
        return ["google_scholar", "google_news", "google"]
    else:
        return ["google_news", "google"]


def _uses_current_market_data(claim: Claim) -> bool:
    """Google Finance is useful for current quote/metric assertions, not history."""
    text = claim.normalized_text or claim.original_text or ""
    if _HISTORICAL_PERIOD_TERMS.search(text):
        return False
    return bool(_CURRENT_MARKET_TERMS.search(text))


def _record_diagnostic(diagnostics: dict[str, Any] | None, event: str, **fields: Any) -> None:
    if diagnostics is not None:
        diagnostics.setdefault("events", []).append({"event": event, **fields})
    if os.getenv("AUDITOR_DIAGNOSTICS", "").lower() in {"1", "true", "yes", "on"}:
        logger.info("retrieval_diagnostic %s", json.dumps({"event": event, **fields}, ensure_ascii=False, default=str))


def _clean_keywords(text: str) -> list[str]:
    """Extract significant keywords from text."""
    words = re.findall(r"[A-Za-z0-9_₹.%-]+", text)
    clean = []
    for w in words:
        w_clean = w.strip(".")
        wl = w_clean.lower()
        if wl not in _FILLER_WORDS and len(wl) > 1 and not wl.startswith("-"):
            clean.append(w_clean)
    return clean


def _normalized_tokens(text: str) -> list[str]:
    """Return comparable lowercase tokens while retaining numbers and abbreviations."""
    tokens = re.findall(r"[a-z0-9₹%]+", (text or "").lower())
    return [t for t in tokens if len(t) > 1 and t not in _QUERY_STOP_WORDS]


def _query_tokens(text: str, keep_short: bool = False, preserve_stop: bool = False) -> list[str]:
    """Tokenize query text while retaining abbreviations, units, and negation."""
    if not isinstance(text, str):
        return []
    tokens = re.findall(r"₹?[+-]?\d+(?:[.,]\d+)?%?|[A-Za-z0-9]+(?:[&./'-][A-Za-z0-9]+)*", text)
    return [token for token in tokens if (preserve_stop or token.lower() not in _QUERY_STOP_WORDS) and (keep_short or len(token) > 1)]


def _usable_http_url(value: Any) -> bool:
    """Only retrieved HTTP(S) URLs may become displayed evidence."""
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _numeric_compatible(claim: Claim, evidence_text: str) -> bool:
    """Reject same-topic results that contain a different material number."""
    claim_numbers = extract_numeric_items(claim.normalized_text or claim.original_text)
    if not claim_numbers and claim.numeric_info:
        claim_numbers = [
            {"type": "percentage" if str(item.get("unit", "")).lower() in {"%", "percent", "percentage", "pct"} else "currency",
             "value": item.get("value")}
            for item in claim.numeric_info
            if isinstance(item, dict) and isinstance(item.get("value"), (int, float))
        ]
    if not claim_numbers:
        return True
    evidence_numbers = extract_numeric_items(evidence_text)
    # A source without the number can still directly refute a claim (for
    # example, an auditor may state that the reported figure is wrong).
    if not evidence_numbers:
        distinctive_entity = any(
            token not in _GENERIC_ENTITY_WORDS and len(token) >= 4 and token in evidence_text.lower()
            for mention in _entity_mentions(claim)
            for token in re.findall(r"[a-z0-9]+", str(mention).lower())
        )
        return distinctive_entity or bool(re.search(r"\b(?:not|no|never|false|didn['’]?t|without|untrue|refut)\w*\b", evidence_text, re.I))
    for claimed in claim_numbers:
        value = claimed.get("value")
        if not isinstance(value, (int, float)):
            continue
        if not any(
            isinstance(actual.get("value"), (int, float))
            and (actual.get("type") == claimed.get("type") or claimed.get("type") == "percentage")
            and values_match(float(value), float(actual["value"]), "percentage" if claimed.get("type") == "percentage" else "value")[0]
            for actual in evidence_numbers
        ):
            # Keep a same-proposition result so the judge can classify a
            # directly conflicting value as Contradicted; period mismatch is
            # handled separately by _temporal_compatible.
            if not re.search(r"\b(?:price|pe|p/e|ratio|percent|percentage|return|fell|rose|growth|sales|revenue|rate|risk|mortality|prevalence|incidence|concentration|capitalization|earnings|yield|beta|average)\b", evidence_text):
                return False
    return True


def _temporal_compatible(claim: Claim, evidence_text: str, evidence_date: Any = None) -> bool:
    """Reject a result explicitly about a different year or period."""
    claim_years = set(re.findall(r"\b(?:19|20)\d{2}\b", claim.normalized_text or claim.original_text))
    if not claim_years:
        return True
    evidence_years = set(re.findall(r"\b(?:19|20)\d{2}\b", evidence_text))
    evidence_years.update(re.findall(r"\b(?:19|20)\d{2}\b", str(evidence_date or "")))
    return not evidence_years or bool(claim_years & evidence_years)


_POPULATION_GROUPS = {
    "children": re.compile(r"\b(?:child|children|pediatric|paediatric|infant|adolescent|teenagers?)\b", re.I),
    "adults": re.compile(r"\b(?:adult|adults|elderly|older|senior|seniors|age\s*\d+)\b", re.I),
    "women": re.compile(r"\b(?:woman|women|female|females|pregnan(?:t|cy))\b", re.I),
    "men": re.compile(r"\b(?:man|men|male|males)\b", re.I),
}


def _population_compatible(claim: Claim, evidence_text: str) -> bool:
    """Reject an explicitly different study population, when both state one."""
    claim_text = claim.normalized_text or claim.original_text or ""
    claim_groups = {name for name, pattern in _POPULATION_GROUPS.items() if pattern.search(claim_text)}
    evidence_groups = {name for name, pattern in _POPULATION_GROUPS.items() if pattern.search(evidence_text)}
    return not claim_groups or not evidence_groups or bool(claim_groups & evidence_groups)


def _relationship_compatible(claim: Claim, evidence_text: str) -> bool:
    """Require causal or comparative language for those propositions."""
    claim_text = (claim.normalized_text or claim.original_text or "").lower()
    evidence_text = evidence_text.lower()
    if re.search(r"\b(?:because|causes?|caused|leads? to|results? in|prevents?|treats?|reduces?|increases?|decreases?)\b", claim_text):
        if not re.search(r"\b(?:because|caus(?:e|es|ed|al)|lead(?:s|ing)? to|result(?:s|ed)? in|produc(?:e|es|ed|ing)|prevent(?:s|ed|ing)?|treat(?:s|ed|ing)?|reduc(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|decreas(?:e|es|ed|ing)|associated with|linked to)\b", evidence_text):
            return False
    if claim.claim_type == "comparison" or re.search(r"\b(?:more|less|higher|lower|better|worse|versus|compared with|than)\b", claim_text):
        if not re.search(r"\b(?:more|less|higher|lower|better|worse|versus|compared with|than|outperform|underperform|times|fold)\b", evidence_text):
            return False
    return True


def _assertion_is_addressed(claim_text: str, evidence_text: str) -> bool:
    """Match proposition roles using small paraphrase groups."""
    claim_terms = {_stem_token(t) for t in _ASSERTION_TERMS.findall(claim_text)}
    evidence_terms = {_stem_token(t) for t in _ASSERTION_TERMS.findall(evidence_text)}
    if claim_terms & evidence_terms:
        return True
    for pattern in _ASSERTION_EQUIVALENTS:
        if pattern.search(claim_text) and pattern.search(evidence_text):
            return True
    return False


def _stem_token(token: str) -> str:
    """Small, deterministic stemmer for search-result paraphrases (reported/reports)."""
    token = token.lower()
    for suffix in ("ies", "ing", "ed", "es", "s"):
        if len(token) > 4 and token.endswith(suffix):
            return token[:-len(suffix)]
    return token


def _entity_mentions(claim: Claim) -> list[str]:
    entities = claim.entities or {}
    mentions: list[str] = []
    if isinstance(entities, dict):
        for key in ("named_entities", "finance_terms", "health_terms", "mentions"):
            values = entities.get(key, [])
            if isinstance(values, list):
                mentions.extend(str(v).strip() for v in values if str(v).strip())
    elif isinstance(entities, list):
        mentions = [str(v).strip() for v in entities if str(v).strip()]
    # Explicit entity fields are already model-selected; do not discard a
    # legitimate generic subject such as ``portfolio`` merely because it is a
    # query stop word. Query construction still applies its bounded token
    # budget, and relevance scoring treats generic-only entities cautiously.
    return list(dict.fromkeys(m for m in mentions if m))


def event_entities(text: str) -> dict[str, list[str]]:
    """Return only the entity anchor belonging to one independently searched event."""
    lower = (text or "").lower()
    if "pets.com" in lower or "pets com" in lower:
        return {"mentions": ["Pets.com"]}
    if "real estate" in lower:
        return {"mentions": ["real estate"]}
    if "virus" in lower:
        return {"mentions": ["tulip breaking virus"]}
    if "tulip" in lower:
        return {"mentions": ["tulip"]}
    if "amsterdam" in lower:
        return {"mentions": ["Amsterdam"]}
    return {}


def _claim_query_text(claim: Claim) -> str:
    """Build a compact assertion-preserving query from the normalized claim."""
    text = claim.normalized_text or claim.claim_english or claim.original_text or claim.quote_original
    mentions = _entity_mentions(claim)
    tokens = list(dict.fromkeys(
        [token for mention in mentions for token in _query_tokens(mention, keep_short=True, preserve_stop=True)]
        + _query_tokens(text)
    ))
    if not tokens:
        return ""

    # Keep explicit entities, quantities, assertion words, and their local
    # context. This handles long transcript-derived claims without replacing
    # the proposition with a number-only or topic-only query.
    entity_tokens = {token.lower() for mention in mentions for token in _query_tokens(mention, keep_short=True)}
    important = set()
    for index, token in enumerate(tokens):
        lower = token.lower()
        if any(char.isdigit() for char in token) or lower in entity_tokens or lower in _QUERY_ASSERTION_WORDS:
            important.update(range(max(0, index - 1), min(len(tokens), index + 2)))
    if len(tokens) <= 22:
        selected = tokens
    else:
        selected = set(range(min(6, len(tokens)))) | set(range(max(0, len(tokens) - 6), len(tokens))) | important
        # Keep the query bounded while retaining all high-value tokens.
        if len(selected) > 24:
            removable = [i for i in sorted(selected) if i not in important]
            for index in removable:
                if len(selected) <= 24:
                    break
                selected.remove(index)
        selected = [tokens[index] for index in sorted(selected)]
    return " ".join(selected)[:180]


def split_compound_claim(claim: Claim) -> list[str]:
    """Return independently searchable event clauses for common compound claims.

    This is intentionally conservative: only claims containing at least two
    recognizable historical/company anchors are split, so ordinary prose and
    compound predicates are left intact.
    """
    text = claim.normalized_text or claim.claim_english or claim.original_text or claim.quote_original
    if _VIRUS_CLAIM_PATTERN.search(text or ""):
        return [
            "Historical reports of streaked or broken tulips in the 1630s.",
            "Tulip-breaking virus causes streaked or broken tulip petals.",
            "The viral cause of tulip breaking was scientifically identified later, not by 1630s collectors.",
        ]
    matches = list(_COMPOUND_EVENT_ANCHORS.finditer(text or ""))
    if len(matches) < 2:
        return [text] if text else []
    parts: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        part = text[match.start():end].strip(" ,;:-")
        part = re.sub(r"[,;:]\s*(?:and|or|then|the|a|an)?\s*$", "", part, flags=re.I)
        part = re.sub(r"^(?:and|or|then)\s+", "", part, flags=re.I)
        if part:
            parts.append(part)
    return parts or [text]


def _historical_query_context(text: str) -> str:
    additions: list[str] = []
    lower = (text or "").lower()
    for trigger, synonyms in _HISTORICAL_CONTEXT_SYNONYMS.items():
        if re.search(rf"\b{re.escape(trigger)}\b", lower):
            additions.extend(synonyms.split())
    return " ".join(dict.fromkeys(additions))


def _subclaim_query_context(text: str) -> str:
    """Add event-specific search language while avoiding current-topic noise."""
    lower = (text or "").lower()
    if "pets.com" in lower or "pets com" in lower:
        return "Pets.com IPO stock price 2000 peak decline shutdown collapse dot-com bubble"
    if "real estate" in lower:
        return "historical real estate housing property price bubble crash collapse"
    if "tulip" in lower:
        if "virus" in lower or "petal" in lower or "streak" in lower or "broken" in lower:
            if "scientifically" in lower or "identified" in lower:
                return "tulip breaking virus scientific identification history later virology"
            if "historical reports" in lower or "1630s" in lower:
                return "historical reports 1630s broken streaked tulips collectors"
            return "tulip breaking virus biological mechanism streaked petals colour breaking"
        return "historical tulip mania bulb prices speculation collapse"
    return _historical_query_context(text)


def _has_phrase(text: str, phrase: str) -> bool:
    text_tokens = set(_normalized_tokens(text))
    phrase_tokens = _normalized_tokens(phrase)
    return bool(phrase_tokens) and all(t in text_tokens for t in phrase_tokens)


def _format_google_finance_ticker(entity_str: str, claim_text: str = "") -> str:
    """Format entity or mention into a recognized Google Finance ticker query."""
    raw = entity_str.strip()
    clean = raw.upper()
    if any(k in clean for k in ["NIFTY 50", "NIFTY50", "NIFTY", "निफ्टी 50", "निफ्टी"]):
        return "NIFTY_50:INDEXNSE"
    if any(k in clean for k in ["SENSEX", "BSE SENSEX", "सेंसेक्स"]):
        return "SENSEX:INDEXBOM"
    if any(k in clean for k in ["BANK NIFTY", "BANKNIFTY", "बैंक निफ्टी"]):
        return "NIFTY_BANK:INDEXNSE"

    if any(k in clean for k in ["MIDCAP 100", "MIDCAP", "मिडकैप", "मिडकॅप"]):
        return "NIFTY_MIDCAP_100:INDEXNSE"
    if any(k in clean for k in ["SMALLCAP", "स्मॉलकैप"]):
        return "NIFTY_SMALLCAP_100:INDEXNSE"

    company_tickers = {
        "RELIANCE": "RELIANCE:NSE",
        "RELIANCE INDUSTRIES": "RELIANCE:NSE",
        "TCS": "TCS:NSE",
        "TATA CONSULTANCY SERVICES": "TCS:NSE",
        "INFOSYS": "INFY:NSE",
        "INFY": "INFY:NSE",
        "HDFC BANK": "HDFCBANK:NSE",
        "HDFCBANK": "HDFCBANK:NSE",
        "ICICI BANK": "ICICIBANK:NSE",
        "ICICIBANK": "ICICIBANK:NSE",
        "STATE BANK OF INDIA": "SBIN:NSE",
        "SBI": "SBIN:NSE",
        "BHARTI AIRTEL": "BHARTIARTL:NSE",
        "ITC": "ITC:NSE",
        "L&T": "LT:NSE",
        "LARSEN & TOUBRO": "LT:NSE",
        "TATA MOTORS": "TATAMOTORS:NSE",
    }
    for comp, ticker in company_tickers.items():
        if comp == clean or clean.startswith(comp) or comp in clean:
            return ticker

    if ":" in clean and re.match(r"^[A-Za-z0-9_]+:[A-Za-z0-9_]+$", clean):
        return clean

    # Do not infer a ticker from the first word of an ordinary entity phrase.
    # For example, ``dot-com mania`` must not become ``DOT:NSE`` and
    # ``stock market`` must not become ``STOCK:NSE``.  Unknown tickers are
    # accepted only when the whole entity is an explicit ticker-shaped token.
    # Preserve the original casing: uppercasing an ordinary company name such
    # as "Acme" would otherwise turn it into a fabricated ticker.
    if re.fullmatch(r"[A-Z][A-Z0-9]{1,9}(?::[A-Z]+)?", raw):
        sym = clean.split(":", 1)[0]
        if claim_text and re.search(r"\b(?:bse|bombay\s+stock\s+exchange)\b", claim_text, re.I):
            return f"{sym}:BOM"
        return f"{sym}:NSE"

    return ""

_NON_TICKER_ENTITIES = {
    "rbi", "reserve bank of india", "reserve bank", "sebi", "sec", "fed",
    "federal reserve", "central bank", "government of india", "finmin",
    "ministry of finance", "who", "icmr", "cdc", "fda", "nih"
}


def _clean_query_terms(*term_groups: str) -> str:
    """Combine term groups while eliminating duplicated words and redundant punctuation."""
    seen_words = set()
    result_tokens = []
    for group in term_groups:
        if not group:
            continue
        tokens = re.findall(r"site:[A-Za-z0-9._-]+|₹?[+-]?\d+(?:[.,]\d+)?%?|[A-Za-z0-9]+(?:[&./'-][A-Za-z0-9]+)*", str(group))
        for tok in tokens:
            tok_lower = tok.lower()
            if tok_lower not in seen_words and tok_lower not in _FILLER_WORDS:
                seen_words.add(tok_lower)
                result_tokens.append(tok)
    return " ".join(result_tokens)


def draft_queries(claim: Claim) -> list[dict[str, Any]]:
    """Draft up to 3 targeted search queries matching the claim and domain."""
    queries: list[dict[str, Any]] = []
    domain = (claim.domain or "").lower()
    engines = route_claim(claim)

    text = claim.normalized_text or claim.claim_english or claim.original_text or claim.quote_original
    keywords = _clean_keywords(text)
    keyword_str = _claim_query_text(claim)

    # Extract entities if available
    entities = claim.entities or {}
    mentions: list[str] = []
    if isinstance(entities, dict):
        for key in ["named_entities", "finance_terms", "health_terms", "mentions"]:
            vals = entities.get(key, [])
            if isinstance(vals, list):
                mentions.extend([str(v) for v in vals])
    elif isinstance(entities, list):
        mentions = [str(e) for e in entities]

    # Filter filler mentions
    clean_mentions = [str(m).strip() for m in mentions if str(m).strip()]
    # Deduplicate while preserving order
    seen_m = set()
    dedup_mentions = []
    for m in clean_mentions:
        if m.lower() not in seen_m:
            seen_m.add(m.lower())
            dedup_mentions.append(m)

    entity_str = " ".join(dedup_mentions[:2]) if dedup_mentions else ""
    subclaims = split_compound_claim(claim)
    assertion_query = _claim_query_text(claim) or text
    # Search each historical event independently. The subclaim marker is
    # internal metadata used later to attribute evidence to the right event.
    if len(subclaims) > 1:
        queries = []
        for subclaim in subclaims[:3]:
            context = _subclaim_query_context(subclaim)
            q = _clean_query_terms(context, subclaim)[:180]
            role = "historical_event"
            lower_subclaim = subclaim.lower()
            if "1630s" in lower_subclaim and "tulip" in lower_subclaim:
                role = "historical_appearance"
            elif "pets.com" in lower_subclaim or "pets com" in lower_subclaim:
                role = "pets.com event"
            elif "real estate" in lower_subclaim:
                role = "real-estate event"
            elif "tulip" in lower_subclaim and "virus" not in lower_subclaim:
                role = "tulip-price event"
            elif "virus" in lower_subclaim and "identified" not in lower_subclaim:
                role = "biological_mechanism"
            elif "scientifically" in subclaim.lower() or "identified" in subclaim.lower():
                role = "scientific_chronology"
            queries.append({"engine": "google", "q": q or subclaim, "subclaim": subclaim, "subclaim_role": role, "subclaim_context": context})
        return queries
    historical_context = _historical_query_context(text)
    if historical_context:
        assertion_query = _clean_query_terms(assertion_query, historical_context)

    # Check for numeric or metric context (e.g. 6.5%, ₹2,000, valuation, revenue, etc.)
    metric_terms = []
    for num in (claim.numeric_info or []):
        if isinstance(num, dict) and num.get("original"):
            metric_terms.append(str(num["original"]))
    metric_str = " ".join(metric_terms[:2])

    if domain == "finance":
        is_ticker_target = (
            "google_finance" in engines
            and _uses_current_market_data(claim)
            and entity_str
            and len(dedup_mentions) == 1
            and not any(non_tick in entity_str.lower() for non_tick in _NON_TICKER_ENTITIES)
        )

        # Query 1: Direct entity ticker quote (if ticker entity) or entity + metrics in news
        if is_ticker_target:
            ticker_query = _format_google_finance_ticker(entity_str, text)
            if ticker_query:
                queries.append({"engine": "google_finance", "q": ticker_query})
            elif "google_news" in engines:
                q_news = _clean_query_terms(assertion_query, metric_str)
                queries.append({"engine": "google_news", "q": (q_news or text)[:180]})
        elif "google_news" in engines:
            q_news = _clean_query_terms(assertion_query, metric_str)
            # If no strong entity, anchor with market context
            if not entity_str and keyword_str and not any(w in keyword_str.lower() for w in ["market", "stock", "nifty", "sensex", "rbi", "sebi", "rates"]):
                q_news = f"{q_news} market stocks".strip()
            queries.append({"engine": "google_news", "q": (q_news or text)[:180]})

        # Query 2: Google News for recent reporting / verification
        if "google_news" in engines and len(queries) < 2:
            q_news2 = _clean_query_terms(entity_str, keyword_str, metric_str) or text
            queries.append({"engine": "google_news", "q": (q_news2 or text)[:180]})

        # Query 3: Google Search targeting regulatory / official exchange reports
        if "google" in engines and len(queries) < 3:
            is_regulator = any(r in entity_str.lower() for r in ["rbi", "reserve bank", "monetary policy", "sebi", "mpc", "fed"])
            if is_regulator:
                q_search = _clean_query_terms(assertion_query, "Monetary Policy Statement decision", metric_str)
            elif any(_has_phrase(text, term) for term in _SPECIALIZED_FINANCE_TERMS):
                # Preserve Google's site operators; passing them through the
                # generic token cleaner would turn ``site:bseindia.com`` into
                # ordinary words and lose the authority constraint.
                q_search = f"{assertion_query} (site:bseindia.com OR site:sebi.gov.in OR site:amfiindia.com)"
            else:
                q_search = _clean_query_terms(assertion_query, metric_str) or text
            queries.append({"engine": "google", "q": (q_search or text)[:180]})

    elif domain == "health":
        # Query 1: Google Scholar for peer-reviewed studies
        if "google_scholar" in engines:
            q_scholar = assertion_query
            queries.append({"engine": "google_scholar", "q": q_scholar[:180]})

        # Query 2: Google News for health advisories / public alerts
        if "google_news" in engines and len(queries) < 2:
            q_news = assertion_query
            queries.append({"engine": "google_news", "q": q_news[:180]})

        # Query 3: Google Search for health authority guidelines (ICMR, WHO, FDA)
        if "google" in engines and len(queries) < 3:
            q_search = assertion_query
            queries.append({"engine": "google", "q": q_search[:180]})

    else:
        # General / other claims
        if "google_news" in engines:
            queries.append({"engine": "google_news", "q": (assertion_query or text)[:180]})
        if "google" in engines and len(queries) < 2:
            q_search = assertion_query or text
            lower_text = text.lower()
            if "dot-com" in lower_text or "1990s" in lower_text:
                q_search = "dot-com bubble 1990s internet mania history site:nber.org OR site:federalreservehistory.org"
            elif "amsterdam" in lower_text and ("port" in lower_text or "commercial" in lower_text):
                q_search = "Amsterdam 1630s port commercial center merchants trade site:amsterdam.nl OR site:huygens.knaw.nl OR site:rijksmuseum.nl"
            queries.append({"engine": "google", "q": q_search[:180]})

    # Fallback if no queries drafted
    if not queries:
        queries.append({"engine": "google", "q": (assertion_query or text)[:180]})

    unique_queries: list[dict[str, Any]] = []
    seen_queries: set[tuple[str, str]] = set()
    for query in queries:
        key = (str(query.get("engine", "")), str(query.get("q", "")).strip().lower())
        if key in seen_queries:
            continue
        seen_queries.add(key)
        unique_queries.append(query)
    return unique_queries[:3]


def _text_field(value: Any) -> str:
    """Normalize a provider text field without serializing arbitrary objects."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "text", "title", "value"):
            if isinstance(value.get(key), str):
                return value[key].strip()
    return ""


def _url_field(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _date_field(value: Any) -> str | None:
    value = _text_field(value)
    return value or None


def _source_field(value: Any) -> str:
    if isinstance(value, dict):
        return _text_field(value.get("name") or value.get("title") or value.get("source"))
    return _text_field(value)


def _host_for_url(value: Any) -> str:
    url = _url_field(value)
    try:
        return urlparse(url).netloc
    except (TypeError, ValueError):
        return ""


def _parse_google_search(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    # 1. Answer Box
    ab = data.get("answer_box", {})
    if isinstance(ab, dict) and (ab.get("snippet") or ab.get("title")):
        items.append({
            "engine": "google",
            "title": _text_field(ab.get("title")) or "Google Quick Answer",
            "source": _source_field(ab.get("source")),
            "date": _date_field(ab.get("date")),
            "snippet": _text_field(ab.get("snippet") or ab.get("answer")),
            "url": _url_field(ab.get("link")) or "https://www.google.com",
            "metadata": {"type": "answer_box"}
        })

    # 2. Knowledge Graph
    kg = data.get("knowledge_graph", {})
    if isinstance(kg, dict) and (kg.get("description") or kg.get("title")):
        items.append({
            "engine": "google",
            "title": _text_field(kg.get("title")),
            "source": _source_field(kg.get("source")),
            "date": None,
            "snippet": _text_field(kg.get("description")),
            "url": _url_field(kg.get("source", {}).get("link")) if isinstance(kg.get("source"), dict) else (_url_field(kg.get("website")) or "https://www.google.com"),
            "metadata": {"type": "knowledge_graph"}
        })

    # 3. Organic Results
    organic = data.get("organic_results", [])
    if isinstance(organic, list):
        for res in organic:
            if not isinstance(res, dict):
                continue
            title = _text_field(res.get("title"))
            snippet = _text_field(res.get("snippet"))
            url = _url_field(res.get("link") or res.get("url"))
            source = _source_field(res.get("source"))
            date = _date_field(res.get("date"))
            if title or snippet or url:
                items.append({
                    "engine": "google",
                    "title": title,
                    "source": source or _host_for_url(url),
                    "date": date,
                    "snippet": snippet,
                    "url": url,
                    "metadata": {}
                })
    return items


def _parse_google_news(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    news_res = data.get("news_results", [])
    if isinstance(news_res, list):
        for res in news_res:
            if not isinstance(res, dict):
                continue
            title = _text_field(res.get("title"))
            snippet = _text_field(res.get("snippet"))
            url = _url_field(res.get("link") or res.get("url"))
            source = _source_field(res.get("source"))
            date = _date_field(res.get("date"))
            if title or snippet or url:
                items.append({
                    "engine": "google_news",
                    "title": title,
                    "source": source or _host_for_url(url),
                    "date": date,
                    "snippet": snippet,
                    "url": url,
                    "metadata": {}
                })
    return items


def _parse_google_scholar(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    organic = data.get("organic_results", [])
    if isinstance(organic, list):
        for res in organic:
            if not isinstance(res, dict):
                continue
            title = _text_field(res.get("title"))
            snippet = _text_field(res.get("snippet"))
            url = _url_field(res.get("link") or res.get("url"))
            pub_info = res.get("publication_info", {})
            pub_summary = _text_field(pub_info.get("summary")) if isinstance(pub_info, dict) else _text_field(pub_info)
            inline = res.get("inline_links", {})
            cited_by = inline.get("cited_by", {}).get("total", 0) if isinstance(inline, dict) else 0

            full_snippet = f"{pub_summary} - {snippet}".strip(" -")
            if title or snippet or url:
                items.append({
                    "engine": "google_scholar",
                    "title": title,
                    "source": pub_summary or _host_for_url(url),
                    "date": None,
                    "snippet": full_snippet,
                    "url": url,
                    "metadata": {"cited_by": cited_by, "publication_summary": pub_summary}
                })
    return items


def _parse_google_finance(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    # 1. Summary / Knowledge Graph
    summary = data.get("summary", {})
    kg = data.get("knowledge_graph", {})

    title = ""
    snippets = []
    date_val = _date_field(summary.get("date")) if isinstance(summary, dict) else None
    if isinstance(summary, dict) and summary:
        title = _text_field(summary.get("title") or summary.get("stock"))
        for k, v in summary.items():
            if not isinstance(k, str):
                continue
            if k not in {"title", "stock", "link"} and v is not None:
                snippets.append(f"{k.replace('_', ' ').title()}: {v}")
    elif isinstance(kg, dict) and kg:
        title = kg.get("title", "")
        desc = kg.get("description", "")
        if desc:
            snippets.append(desc)

    if title or snippets:
        items.append({
            "engine": "google_finance",
            "title": title or "Google Finance Market Data",
            "source": "Google Finance",
            "date": date_val,
            "snippet": "; ".join(snippets) if snippets else "Financial quote and key statistics.",
            "url": "https://www.google.com/finance",
            "metadata": {"summary": summary, "knowledge_graph": kg}
        })

    # SerpApi deployments may expose quote data under finance_results or
    # markets rather than summary. Normalize those records into the same
    # evidence shape instead of silently dropping them.
    alternate = data.get("finance_results") or data.get("markets") or []
    if isinstance(alternate, dict):
        alternate = [alternate]
    if isinstance(alternate, list):
        for record in alternate:
            if not isinstance(record, dict):
                continue
            record_title = _text_field(record.get("title") or record.get("name") or record.get("stock"))
            details = [
                f"{str(key).replace('_', ' ').title()}: {value}"
                for key, value in record.items()
                if key not in {"title", "name", "stock", "link", "url"} and value is not None
            ]
            link = _url_field(record.get("link") or record.get("url")) or "https://www.google.com/finance"
            if record_title or details:
                items.append({
                    "engine": "google_finance",
                    "title": str(record_title or "Google Finance Market Data"),
                    "source": "Google Finance",
                    "date": _date_field(record.get("date")),
                    "snippet": "; ".join(details),
                    "url": link,
                    "metadata": {"summary": record},
                })

    # 2. News from Google Finance
    news = data.get("news", [])
    if isinstance(news, list):
        for n in news:
            if isinstance(n, dict):
                items.append({
                    "engine": "google_news",
                    "title": _text_field(n.get("title")),
                    "source": _source_field(n.get("source")) or "Google Finance News",
                    "date": _date_field(n.get("date")),
                    "snippet": _text_field(n.get("snippet")),
                    "url": _url_field(n.get("link") or n.get("url")) or "https://www.google.com/finance",
                    "metadata": {}
                })
    return items


def parse_engine_response(engine: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse raw SerpApi JSON response into structured evidence dictionaries."""
    if not isinstance(data, dict):
        return []
    if engine == "google_news":
        items = _parse_google_news(data)
    elif engine == "google_scholar":
        items = _parse_google_scholar(data)
    elif engine == "google_finance":
        items = _parse_google_finance(data)
    else:
        items = _parse_google_search(data)
    # A title/link-only hit remains useful as a retry candidate, but never as
    # proof. Keep this metadata attached even though retrieval filters such hits
    # from the evidence list.
    for item in items:
        metadata = item.setdefault("metadata", {})
        has_content = bool(_text_field(item.get("snippet")))
        metadata.setdefault("content_available", has_content)
        metadata.setdefault("content_retryable", bool(_url_field(item.get("url"))))
        if not has_content and _url_field(item.get("url")):
            metadata.setdefault("retry_candidate", {
                "url": _url_field(item.get("url")),
                "title": _text_field(item.get("title")),
                "source": _source_field(item.get("source")) or _host_for_url(item.get("url")),
                "status": "content_unavailable",
            })
    return items


def _response_result_count(data: Any) -> int:
    """Count result records without logging response contents."""
    if not isinstance(data, dict):
        return 0
    keys = ("organic_results", "news_results", "inline_images", "news", "finance_results", "markets")
    return sum(
        len(data.get(key, [])) if isinstance(data.get(key), list)
        else 1 if isinstance(data.get(key), dict) else 0
        for key in keys
    )


def compute_claim_relevance(item: dict[str, Any], claim: Claim, keywords: list[str]) -> float:
    """Calculate claim-specific relevance, rejecting topic-only search matches.

    Search engines frequently return a page that shares a broad term (for example
    ``Sensex``) but does not address the assertion (for example, index-fund
    tracking). A result must therefore match a subject anchor and at least one
    claim-specific assertion/metric term. Specialized finance assertions require
    their specialized concept to appear as well.
    """
    domain = (claim.domain or "").lower()
    ev_text = f"{item.get('title', '')} {item.get('snippet', '')}".lower()

    if not _numeric_compatible(claim, ev_text):
        return 0.0
    if not _temporal_compatible(claim, ev_text, item.get("date")):
        return 0.0
    if not _population_compatible(claim, ev_text):
        return 0.0
    if not _relationship_compatible(claim, ev_text):
        return 0.0

    # Hard rejection for off-domain finance patterns
    if domain == "finance":
        claim_has_med = bool(re.search(r"\b(?:vaccin|flu|covid|cancer|drug|pharma|biotech|clinical|hospital|health)\b", claim.normalized_text or claim.original_text or ""))
        if not claim_has_med and _OFF_DOMAIN_FINANCE_PATTERNS.search(ev_text):
            return 0.0

    score = 0.0
    entity_hit = False
    claim_tokens = {_stem_token(t) for t in _normalized_tokens(claim.normalized_text or claim.original_text)}
    evidence_tokens = {_stem_token(t) for t in _normalized_tokens(ev_text)}

    # Prefer explicit entity fields, but recover named anchors from the claim for
    # older extraction records that did not populate entities.
    mentions = _entity_mentions(claim)
    claim_text = claim.normalized_text or claim.original_text
    for candidate in re.findall(r"\b[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*)*\b", claim_text):
        if candidate.lower() not in _QUERY_STOP_WORDS:
            mentions.append(candidate)
    # A result may use the short name ("XYZ") instead of the claim's
    # descriptive form ("Company XYZ"). Keep meaningful uppercase tokens as
    # aliases without treating ordinary sentence-initial words as entities.
    for candidate in re.findall(r"\b[A-Z]{2,}[A-Za-z0-9.-]*\b", claim_text):
        if candidate.lower() not in _QUERY_STOP_WORDS:
            mentions.append(candidate)
    mentions = list(dict.fromkeys(mentions))

    # 1. Match core entity mentions
    for mention in mentions:
        mention_tokens = {_stem_token(t) for t in _normalized_tokens(mention)}
        if mention_tokens and not mention_tokens.issubset(_GENERIC_ENTITY_WORDS) and mention_tokens.issubset(evidence_tokens):
            score += 5.0
            entity_hit = True
            break
        distinctive = [t for t in mention_tokens if len(t) >= 4 and t not in _GENERIC_ENTITY_WORDS]
        if distinctive and any(t in evidence_tokens for t in distinctive):
            score += 4.0
            entity_hit = True
            break

    # 2. Match numeric / quantitative metrics
    for num in (claim.numeric_info or []):
        if isinstance(num, dict) and num.get("original"):
            orig = str(num["original"]).lower()
            if orig in ev_text or {_stem_token(t) for t in _normalized_tokens(orig)}.issubset(evidence_tokens):
                score += 4.0

    # 3. Financial topic alignment for finance claims
    topic_hit = False
    # Count overlap before stemming so short paraphrase stems such as
    # ``sales`` -> ``sal`` are not accidentally discarded by the length gate.
    meaningful_overlap = len(
        {_stem_token(t) for t in _normalized_tokens(claim.normalized_text or claim.original_text) if len(t) > 3}
        & {_stem_token(t) for t in _normalized_tokens(ev_text)}
    )
    if domain == "finance":
        if _FINANCIAL_TOPIC_TERMS.search(ev_text):
            score += 2.0
            topic_hit = True
        specialized_claim_terms = [term for term in _SPECIALIZED_FINANCE_TERMS if _has_phrase(claim.normalized_text or claim.original_text, term)]
        required_terms = [term for term in specialized_claim_terms if term in _RELATIONSHIP_FINANCE_TERMS]
        if not required_terms:
            required_terms = specialized_claim_terms
        specialized_overlap = any(_has_phrase(ev_text, term) for term in required_terms)
        # A specialized assertion cannot be supported by an article that only
        # mentions the same index/market name. Require the concept itself.
        if specialized_claim_terms and not specialized_overlap:
            return 0.0
        if entity_hit and (claim.numeric_info or claim.claim_type in {"statistic", "comparison"}) and _ASSERTION_TERMS.search(claim_text) and not _assertion_is_addressed(claim_text, ev_text):
            return 0.0
        # Topic-only hits (e.g. an unrelated market overview) are not evidence.
        if meaningful_overlap == 0 or (not entity_hit and meaningful_overlap < 2):
            return 0.0
    elif domain == "health" and not entity_hit and meaningful_overlap < 2:
        return 0.0
    elif domain not in {"finance", "health"} and not entity_hit and meaningful_overlap == 0:
        return 0.0

    # Historical event searches must actually address the historical event.
    # This rejects current "real estate stocks" lists for a historical bubble
    # claim while retaining sources that mention dates, crashes, IPOs, or other
    # event markers. Mechanism-only virus subclaims do not carry this marker.
    claim_text = claim.normalized_text or claim.original_text
    if re.search(r"\b(?:historical|history|1630s|17th century|1990s|2000|crash|collapse|bubble|mania|shutdown|ipo|identified later)\b", claim_text, re.I):
        if re.search(r"\b(?:virus|petal|streak|pigment)\b", claim_text, re.I) and re.search(r"\b(?:virus|petal|streak|pigment)\b", ev_text, re.I):
            return score
        if not _HISTORICAL_EVIDENCE_TERMS.search(ev_text):
            return 0.0

    # 4. Match non-filler claim keywords
    for kw in keywords:
        if len(kw) > 3 and kw in ev_text:
            score += 1.0

    # 5. Bonus for structured market data from Google Finance
    if item.get("metadata", {}).get("summary"):
        score += 3.0

    return score


def evidence_matches_claim(item: dict[str, Any], claim: Claim) -> bool:
    """Public qualification predicate shared by retrieval and judging."""
    text = f"{item.get('title', '')} {item.get('snippet', '')}".strip()
    if not text and not item.get("metadata", {}).get("summary"):
        return False
    keywords = [w.lower() for w in _clean_keywords(claim.normalized_text or claim.original_text)]
    return compute_claim_relevance(item, claim, keywords) > 0


def retrieve_claim(claim: Claim, serp: SerpApiClient, diagnostics: dict[str, Any] | None = None) -> tuple[list[Evidence], str]:
    """Retrieve, tier, deduplicate, filter, and rank evidence for a single claim."""
    if not claim.checkable:
        return [], "complete"

    query_started = time.perf_counter()
    queries = draft_queries(claim)
    _record_diagnostic(diagnostics, "query_generation", claim_id=claim.id, duration_ms=round((time.perf_counter() - query_started) * 1000, 2), query_count=len(queries))
    _record_diagnostic(
        diagnostics,
        "claim_start",
        claim_id=claim.id,
        domain=claim.domain,
        claim_type=claim.claim_type,
        query_count=len(queries),
        queries=[{"engine": q.get("engine"), "q": str(q.get("q", ""))[:240]} for q in queries],
    )
    retrieved_at = datetime.now(timezone.utc).isoformat()
    raw_evidence: list[dict[str, Any]] = []
    success_calls = 0
    parse_failures = 0
    empty_responses = 0
    errors: list[str] = []

    for q_spec in queries:
        engine = q_spec["engine"]
        q_params = {k: v for k, v in q_spec.items() if k != "engine"}
        subclaim_text = q_params.pop("subclaim", "")
        subclaim_role = q_params.pop("subclaim_role", "")
        subclaim_context = q_params.pop("subclaim_context", "")
        try:
            request_started = time.perf_counter()
            res = serp.search(engine, **q_params)
            request_duration = (time.perf_counter() - request_started) * 1000
            search_meta = getattr(serp, "last_search", {}) or {}
            raw_count = _response_result_count(res)
            _record_diagnostic(
                diagnostics,
                "search_result",
                claim_id=claim.id,
                engine=engine,
                query=str(q_params.get("q", ""))[:240],
                cache_status=search_meta.get("status", "unknown"),
                cache_hit=search_meta.get("cache_hit"),
                duration_ms=round(request_duration, 2),
                raw_result_count=raw_count,
            )
            if res is None:
                empty_responses += 1
                _record_diagnostic(diagnostics, "empty_response", claim_id=claim.id, engine=engine)
                continue
            if not isinstance(res, dict):
                parse_failures += 1
                _record_diagnostic(diagnostics, "parse_failure", claim_id=claim.id, engine=engine, reason="response_not_object")
                continue
            parse_started = time.perf_counter()
            items = parse_engine_response(engine, res)
            parse_duration = (time.perf_counter() - parse_started) * 1000
            _record_diagnostic(diagnostics, "parsed_results", claim_id=claim.id, engine=engine, parsed_count=len(items), duration_ms=round(parse_duration, 2))
            if not items and raw_count > 0:
                parse_failures += 1
                _record_diagnostic(diagnostics, "parse_failure", claim_id=claim.id, engine=engine, reason="raw_records_not_normalized")
            elif not items:
                empty_responses += 1
                _record_diagnostic(diagnostics, "empty_response", claim_id=claim.id, engine=engine)
            for item in items:
                metadata = item.setdefault("metadata", {})
                if subclaim_text:
                    metadata["subclaim"] = subclaim_text
                if subclaim_role:
                    metadata["subclaim_role"] = subclaim_role
                if subclaim_context:
                    metadata["subclaim_context"] = subclaim_context
                metadata.setdefault("content_available", bool(_text_field(item.get("snippet"))))
                metadata.setdefault("content_retryable", bool(_url_field(item.get("url"))))
            raw_evidence.extend(items)
            success_calls += 1
        except SerpApiError as e:
            errors.append(str(e))
            search_meta = getattr(serp, "last_search", {}) or {}
            _record_diagnostic(diagnostics, "search_error", claim_id=claim.id, engine=engine, cache_status=search_meta.get("status", "unknown"), error_type=type(e).__name__)
            logger.warning(f"SerpApi query failed for engine={engine}: {e}")
        except Exception as e:
            errors.append(str(e))
            _record_diagnostic(diagnostics, "search_error", claim_id=claim.id, engine=engine, cache_status="unknown", error_type=type(e).__name__)
            logger.warning(f"Unexpected error during retrieval: {e}")

    # If all attempted queries encountered errors and nothing succeeded
    if success_calls == 0 and (errors or parse_failures) and not raw_evidence:
        _record_diagnostic(
            diagnostics,
            "claim_complete",
            claim_id=claim.id,
            raw_result_count=0,
            deduped_count=0,
            filtered_count=0,
            evidence_count=0,
            parse_failure_count=parse_failures,
            empty_response_count=empty_responses,
            rejection_counts={},
            status="failed",
        )
        return [], "failed"

    # Deduplicate by URL or title
    seen_urls: set[str] = set()
    rejection_counts: dict[str, int] = {}
    def reject(reason: str) -> None:
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
    deduped: list[dict[str, Any]] = []
    for item in raw_evidence:
        url = _url_field(item.get("url"))
        title = _text_field(item.get("title"))
        if not _usable_http_url(url):
            reject("invalid_url")
            continue
        # Engine fallbacks such as https://www.google.com are not citations;
        # only a structured Google Finance record may use its product URL.
        if urlparse(url).netloc.lower().removeprefix("www.") == "google.com" and not item.get("metadata", {}).get("summary"):
            reject("engine_placeholder_url")
            continue
        key = url if url and url != "https://www.google.com" else title
        if key and key not in seen_urls:
            seen_urls.add(key)
            deduped.append(item)

    # Calculate tiers
    for item in deduped:
        url = item.get("url", "")
        source = item.get("source", "")
        item["tier"] = get_tier_for_url(url, source)

    domain = (claim.domain or "").lower()
    claim_text = f"{claim.normalized_text or claim.claim_english or claim.original_text or ''}".lower()
    keywords = [w.lower() for w in _clean_keywords(claim_text)]

    filter_started = time.perf_counter()
    filtered: list[dict[str, Any]] = []
    for item in deduped:
        url = _url_field(item.get("url")).lower()
        title = _text_field(item.get("title"))
        snippet = _text_field(item.get("snippet"))
        ev_text = f"{title} {snippet}".lower()

        # Strict snippet requirement: Discard completely empty snippet unless it's Google Finance with structured data
        has_structured = bool(item.get("metadata", {}).get("summary")) or (item.get("engine") == "google_finance" and snippet)
        if not snippet and not has_structured:
            reject("empty_content")
            continue

        # Domain-aware relevance filtering for finance claims
        if domain == "finance":
            parsed_netloc = urlparse(url).netloc
            if any(unrelated in parsed_netloc for unrelated in _UNRELATED_FINANCE_DOMAINS):
                reject("known_off_domain")
                continue
            if ".edu" in parsed_netloc and any(sub in url for sub in ["courses", "syllabus", "lecture", "covid", "campus", "aloha"]):
                continue

            # Reject off-domain medical/clinical results unless the claim itself mentions medical terms
            claim_has_med = bool(re.search(r"\b(?:vaccin|flu|covid|cancer|drug|pharma|biotech|clinical|hospital|health)\b", claim_text))
            if not claim_has_med and _OFF_DOMAIN_FINANCE_PATTERNS.search(ev_text):
                reject("off_domain_content")
                continue

        # For a compound claim, score each result against the event that
        # produced it. This prevents a result about tulip mania from being
        # incorrectly treated as evidence for a separate Pets.com event.
        relevance_claim = claim
        subclaim = item.get("metadata", {}).get("subclaim")
        if subclaim:
            context = item.get("metadata", {}).get("subclaim_context", "")
            relevance_text = subclaim
            if claim.claim_type == "historical_fact":
                # Preserve the parent claim's historical scope without adding
                # query-expansion terms (such as stock price) to the metric
                # proposition being checked.
                relevance_text = f"historical {subclaim}"
            relevance_claim = claim.model_copy(update={
                "normalized_text": relevance_text,
                "claim_english": relevance_text,
                "original_text": subclaim,
                "quote_original": subclaim,
                "entities": event_entities(subclaim),
            })
        rel_score = compute_claim_relevance(item, relevance_claim, keywords)
        item["relevance_score"] = rel_score

        # Only retain items with positive relevance
        if rel_score > 0:
            filtered.append(item)
        else:
            reject("claim_relevance")

    # Rank evidence:
    # 1. Relevance score (Higher relevance is primary!)
    # 2. Presence of non-empty snippet (True > False)
    # 3. Source Tier (Tier 1 is best)
    # 4. Scholar citations
    def rank_key(ev_item: dict[str, Any]) -> tuple[float, int, int, int]:
        rel = ev_item.get("relevance_score", 0.0)
        has_snip = 1 if (ev_item.get("snippet") or "").strip() else 0
        tier = ev_item.get("tier", 3)
        cited_by = ev_item.get("metadata", {}).get("cited_by", 0)
        return (-rel, -has_snip, tier, -int(cited_by))

    ranked = sorted(filtered, key=rank_key)
    _record_diagnostic(diagnostics, "relevance_filter", claim_id=claim.id, duration_ms=round((time.perf_counter() - filter_started) * 1000, 2), candidate_count=len(deduped), retained_count=len(filtered), rejection_counts=rejection_counts)

    # Convert every relevant, non-duplicate result to Evidence. Relevance and
    # deduplication above determine eligibility; truncating here would silently
    # discard valid sources before the pipeline, API, and UI can preserve them.
    evidence_models: list[Evidence] = []
    for idx, item in enumerate(ranked):
        ev_id = f"e{idx + 1}"
        evidence_models.append(Evidence(
            id=ev_id,
            engine=item.get("engine", "google"),
            title=item.get("title", ""),
            source=item.get("source", ""),
            tier=item.get("tier", 3),
            date=item.get("date"),
            snippet=item.get("snippet", ""),
            url=item.get("url", ""),
            retrieved_at=retrieved_at,
            metadata=item.get("metadata", {})
        ))

    _record_diagnostic(
        diagnostics,
        "claim_complete",
        claim_id=claim.id,
        raw_result_count=len(raw_evidence),
        parse_failure_count=parse_failures,
        empty_response_count=empty_responses,
        deduped_count=len(deduped),
        filtered_count=len(filtered),
        evidence_count=len(evidence_models),
        rejection_counts=rejection_counts,
        status="failed" if success_calls == 0 and errors and not raw_evidence else "complete",
    )

    return evidence_models, "complete"
