"""Deterministic and robust numeric claim verification against retrieved evidence."""

import math
import re
from typing import Any
from .schemas import Claim, Evidence

_PERCENT_PATTERN = re.compile(
    r"([+-]?\d+(?:\.\d+)?)\s*(?:%|per\s*cent|percent|percentage|प्रतिशत|फीसदी)",
    re.IGNORECASE
)

_INDIAN_DENOM_PATTERN = re.compile(
    r"(?:₹|rs\.?|inr|\$|usd)?\s*([+-]?\d+(?:\.\d+)?)\s*(lakh|lac|crore|cr|k|m|million|b|billion|bn|t|trillion|tn)\b",
    re.IGNORECASE
)

_CURRENCY_PATTERN = re.compile(
    r"(?:₹|rs\.?|inr|\$|usd|eur|gbp)\s*([+-]?\d+(?:,\d+)*(?:\.\d+)?)",
    re.IGNORECASE
)

_PE_PATTERN = re.compile(
    r"(?:price\s*to\s*earnings|\(?p/e\)?|pe\s*ratio|valuation)\s*(?:\(?p/e\)?|\(?pe\)?)?\s*(?:ratio)?\s*(?:of|is|at|:|currently|trading|stands|around|\s)*\s*([+-]?\d+(?:\.\d+)?)",
    re.IGNORECASE
)

_MULTIPLIER_PATTERN = re.compile(
    r"\b([+-]?\d+(?:\.\d+)?)\s*(?:x|times|fold|गुना)\b",
    re.IGNORECASE
)

_DENOMINATIONS = {
    "k": 1e3,
    "lakh": 1e5,
    "lac": 1e5,
    "m": 1e6,
    "million": 1e6,
    "crore": 1e7,
    "cr": 1e7,
    "b": 1e9,
    "billion": 1e9,
    "bn": 1e9,
    "t": 1e12,
    "trillion": 1e12,
    "tn": 1e12,
}


def _clean_number(value: Any) -> float | None:
    """Normalize one numeric field without coercing arbitrary objects to text."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if not isinstance(value, str):
        return None
    try:
        clean = value.replace(",", "").strip()
        parsed = float(clean)
        return parsed if math.isfinite(parsed) else None
    except (ValueError, TypeError):
        return None


def extract_numeric_items(text: str) -> list[dict[str, Any]]:
    """Extract numeric mentions with their type, raw string, and parsed value."""
    results = []
    if not isinstance(text, str) or not text:
        return results

    # 1. P/E Ratios
    for m in _PE_PATTERN.finditer(text):
        val = _clean_number(m.group(1))
        if val is not None:
            results.append({
                "type": "pe_ratio",
                "raw": m.group(0),
                "value": val,
                "unit": "ratio",
                "start": m.start(),
            })

    # 2. Percentages
    for m in _PERCENT_PATTERN.finditer(text):
        val = _clean_number(m.group(1))
        if val is not None:
            results.append({
                "type": "percentage",
                "raw": m.group(0),
                "value": val,
                "unit": "%",
                "start": m.start(),
            })

    # 3. Indian Denominations (Lakh, Crore, Billion, etc.)
    for m in _INDIAN_DENOM_PATTERN.finditer(text):
        base_val = _clean_number(m.group(1))
        denom_str = m.group(2).lower()
        multiplier = _DENOMINATIONS.get(denom_str, 1.0)
        if base_val is not None:
            results.append({
                "type": "denominated_value",
                "raw": m.group(0),
                "value": base_val * multiplier,
                "unit": denom_str,
                "start": m.start(),
            })

    # 4. Currency
    for m in _CURRENCY_PATTERN.finditer(text):
        val = _clean_number(m.group(1))
        if val is not None:
            # check if not already part of denomination
            if not any(abs(r["start"] - m.start()) < 5 for r in results if r["type"] == "denominated_value"):
                results.append({
                    "type": "currency",
                    "raw": m.group(0),
                    "value": val,
                    "unit": "currency",
                    "start": m.start(),
                })

    # 5. Multipliers (e.g. 10x, 2x)
    for m in _MULTIPLIER_PATTERN.finditer(text):
        val = _clean_number(m.group(1))
        if val is not None:
            results.append({
                "type": "multiplier",
                "raw": m.group(0),
                "value": val,
                "unit": "x",
                "start": m.start(),
            })

    return results


def values_match(claimed: float, actual: float, unit_type: str, tolerance: float = 0.05) -> tuple[bool, float]:
    """Check if claimed value matches actual within tolerance.

    Returns (is_match, percentage_difference).
    """
    if math.isclose(claimed, actual, rel_tol=1e-5, abs_tol=1e-5):
        return True, 0.0

    # For percentages, also check absolute difference tolerance (e.g. 0.5% diff)
    if unit_type == "percentage":
        abs_diff = abs(claimed - actual)
        if abs_diff <= 0.5:
            return True, abs_diff
        denom = max(abs(actual), 1.0)
        rel_diff = abs_diff / denom
        return rel_diff <= tolerance, rel_diff * 100.0

    # For large numbers / currencies / denominations
    denom = max(abs(actual), 1e-9)
    rel_diff = abs(claimed - actual) / denom
    return rel_diff <= tolerance, rel_diff * 100.0


_HISTORICAL_MARKERS = re.compile(
    r"\b(?:in\s+20\d{2}|during\s+20\d{2}|last\s+(?:year|quarter|month)|past\s+(?:year|quarter|month|decade|5\s+years)|historical\s+averages?|fell\s+\d+%\s+in|June\s+quarter|March\s+quarter|September\s+quarter|December\s+quarter|q[1-4]\s+fy\s*\d{2})\b",
    re.I
)

_PREDICTIVE_CUES = re.compile(
    r"\b(?:"
    r"will\s+(?:most\s+likely\s+|likely\s+|probably\s+)?(?:maintain|hike|cut|raise|keep|increase|decrease|leave|pause|hold|remain)|"
    r"expected\s+to|likely\s+to|projected\s+to|predicted\s+to|poised\s+to|set\s+to|anticipated\s+to|"
    r"may\s+(?:maintain|hike|cut|keep|hold|raise|increase|decrease)|"
    r"could\s+(?:maintain|hike|cut|keep|hold|raise|increase|decrease)|"
    r"forecasts?\s+that|chances\s+of|poll\s+expects|economists\s+expect|analysts\s+expect|ahead\s+of\s+the\s+(?:mpc|rbi|meeting|policy)"
    r")\b",
    re.I
)

_COMPLETED_EVENT_CONFIRMATION = re.compile(
    r"\b(?:"
    r"decided\s+to|unanimously\s+decided|has\s+decided|kept\s+(?:the\s+|its\s+)?(?:repo|policy|benchmark|interest|key)|"
    r"maintained\s+(?:the\s+|its\s+)?(?:repo|policy|benchmark|interest|key)|"
    r"held\s+(?:the\s+|its\s+)?(?:repo|policy|benchmark|interest|key)|"
    r"voted\s+(?:unanimously\s+)?to|announced\s+on\s+[a-zA-Z]+\s+that|announced\s+that\s+it\s+(?:has\s+)?|"
    r"remains\s+unchanged\s+at|remained\s+unchanged\s+at|left\s+(?:the\s+|its\s+)?(?:repo|policy|benchmark|interest|key)\s+rate\s+unchanged|"
    r"has\s+(?:kept|maintained|held|raised|hiked|cut)"
    r")\b",
    re.I
)

_COMPLETED_CLAIM_MARKERS = re.compile(
    r"\b(?:kept|maintained|held|hiked|cut|raised|fell|rose|dropped|grew|reported|posted|announced|decided|voted|remained|decreased|increased|reached)\b",
    re.I
)


def check_numeric_claim(claim: Claim, evidence: list[Evidence]) -> tuple[dict[str, Any] | None, str]:
    """Compare numeric statements in a claim against retrieved evidence."""
    # Collect numeric items from claim
    claim_text = f"{claim.normalized_text} {claim.original_text} {claim.quote_original} {claim.claim_english}"
    claim_nums = extract_numeric_items(claim_text)
    is_historical = bool(_HISTORICAL_MARKERS.search(claim_text))
    is_completed_claim = bool(_COMPLETED_CLAIM_MARKERS.search(claim_text)) or is_historical or (
        claim.claim_type and claim.claim_type.lower() in {"verifiable_fact", "historical_fact", "statistic"}
    )

    # Also check structured numeric_info on claim
    if not claim_nums and claim.numeric_info:
        for item in claim.numeric_info:
            if not isinstance(item, dict):
                continue
            val = _clean_number(item.get("value"))
            if val is not None:
                claim_nums.append({
                    "type": "numeric_info",
                    "raw": item.get("original", str(val)),
                    "value": val,
                    "unit": item.get("unit", ""),
                    "start": 0,
                })

    if not claim_nums or not evidence:
        return None, "no_numeric_data"

    best_match = None
    best_diff = float("inf")

    # Scan each evidence item
    for ev in evidence:
        # Do not use real-time quote without historical date context for past-dated historical claims
        if is_historical and ev.engine == "google_finance" and not ev.date:
            continue

        # Check snippet and title
        evidence_text = f"{ev.title} {ev.snippet}"

        # Do not treat forward-looking speculative previews as factual proof of completed historical events
        is_predictive = bool(_PREDICTIVE_CUES.search(evidence_text))
        has_confirmation = bool(_COMPLETED_EVENT_CONFIRMATION.search(evidence_text))
        if is_completed_claim and is_predictive and not has_confirmation:
            continue

        # Check structured metadata first (e.g. from Google Finance)
        meta = ev.metadata or {}
        summary = meta.get("summary", {}) if isinstance(meta.get("summary"), dict) else {}
        kg = meta.get("knowledge_graph", {}) if isinstance(meta.get("knowledge_graph"), dict) else {}

        evidence_nums = extract_numeric_items(evidence_text)

        # Check structured Google Finance fields
        if summary:
            for k in ["price", "pe_ratio", "previous_close", "market_cap", "fifty_two_week_high", "fifty_two_week_low"]:
                if k in summary:
                    val = _clean_number(summary[k])
                    if val is not None:
                        evidence_nums.append({
                            "type": "pe_ratio" if "pe" in k else "currency",
                            "raw": f"{k}: {summary[k]}",
                            "value": val,
                            "unit": k,
                            "start": 0,
                        })

        # Match claim numbers to evidence numbers
        for c_num in claim_nums:
            for e_num in evidence_nums:
                # Require compatible types if known
                if c_num["type"] != e_num["type"] and c_num["type"] != "numeric_info" and e_num["type"] != "numeric_info":
                    continue

                is_match, diff_pct = values_match(c_num["value"], e_num["value"], c_num["type"])

                is_better_diff = diff_pct < best_diff
                is_equal_diff_higher_tier = (
                    math.isclose(diff_pct, best_diff, abs_tol=1e-5)
                    and best_match is not None
                    and ev.tier < best_match.get("source_tier", 3)
                )

                if is_better_diff or is_equal_diff_higher_tier:
                    best_diff = diff_pct
                    session_info = f" (market session: {ev.date})" if ev.date else ""
                    best_match = {
                        "field": c_num["type"],
                        "claimed": c_num["value"],
                        "actual": e_num["value"],
                        "claimed_raw": c_num["raw"],
                        "actual_raw": e_num["raw"],
                        "within_tolerance": is_match,
                        "diff_pct": round(diff_pct, 2),
                        "source_evidence_id": ev.id,
                        "source_tier": ev.tier,
                        "source_url": ev.url,
                        "date": ev.date,
                        "explanation": (
                            f"Claimed {c_num['raw']} matches {ev.source} quote of {e_num['raw']}{session_info} (difference: {round(diff_pct, 2)}%)."
                            if is_match else
                            f"Claimed {c_num['raw']} contradicts {ev.source} quote of {e_num['raw']}{session_info} (difference: {round(diff_pct, 2)}%)."
                        )
                    }

    if best_match is not None:
        return best_match, "complete"

    return None, "no_matching_metric"
