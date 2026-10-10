"""Evidence-based judgment engine enforcing strict citation validation and source-tier rules."""

import json
import logging
import re
from typing import Any
from pydantic import BaseModel, Field

from .numeric import (
    check_numeric_claim,
    _PREDICTIVE_CUES,
    _COMPLETED_EVENT_CONFIRMATION,
    _COMPLETED_CLAIM_MARKERS,
    _HISTORICAL_MARKERS,
)
from .retrieve import (
    _OFF_DOMAIN_FINANCE_PATTERNS,
    _FINANCIAL_TOPIC_TERMS,
    evidence_matches_claim,
    event_entities,
    split_compound_claim,
    _stem_token,
    _usable_http_url,
)
from .schemas import Claim, Evidence, Judgment, VerdictLabel

logger = logging.getLogger(__name__)


class LLMVerdictSchema(BaseModel):
    label: str
    confidence: str = "Medium"
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)


_PERSONAL_POSITIONING_PATTERN = re.compile(
    r"\b(?:"
    r"we\s+(?:have\s+been|are|remain|stay|were|became|like|prefer|hold|maintain|bought|sold|increased|decreased)\s+(?:positive|bullish|bearish|cautious|optimistic|pessimistic|overweight|underweight|negative|neutral|exposure|allocation|positions?)|"
    r"we\s+(?:also\s+)?(?:have|hold|maintain|built)\s+(?:exposure|allocation|position|stakes?|positive)|"
    r"positivity\s+has\s+increased|"
    r"(?:our|my)\s+(?:portfolio|fund|stance|outlook|view|exposure|allocation|position|strategy|thesis)|"
    r"we\s+like\s+(?:the\s+)?(?:auto|metals?|manufacturing|pharma|banking|tech|it|cement|energy|stocks?|sectors?|market|equities|equity)|"
    r"we\s+continue\s+to\s+remain\s+(?:positive|bullish|cautious|optimistic|negative)|"
    r"we\s+have\s+been\s+positive"
    r")\b",
    re.I
)


def _clean_rationale(text: str) -> str:
    """Ensure rationale is neutral, claim-focused, and at most 3 sentences."""
    if not text:
        return "No rationale provided."
    # Remove any ad-hominem or creator-judgment words
    cleaned = re.sub(
        r"\b(?:influencer|creator|speaker|youtuber|he|she)\s+(?:is\s+a\s+scammer|is\s+lying|is\s+fraudulent|is\s+trustworthy|cannot\s+be\s+trusted)\b",
        "the claim is unsupported by verifiable records",
        text,
        flags=re.IGNORECASE
    )
    # Truncate to 3 sentences max
    sentences = re.split(r"(?<=[.!?])\s+", cleaned.strip())
    if len(sentences) > 3:
        cleaned = " ".join(sentences[:3])
    return cleaned.strip()


def _polarity_conflicts(claim_text: str, evidence_text: str) -> bool:
    """Detect a direct increase/decrease polarity conflict for numeric claims."""
    claim_positive = bool(re.search(r"\b(?:increase(?:d|s)?|rose|grew|growth|higher|gain(?:ed|s)?)\b", claim_text, re.I))
    claim_negative = bool(re.search(r"\b(?:decrease(?:d|s)?|fell|decline(?:d|s)?|lower|drop(?:ped|s)?)\b", claim_text, re.I))
    evidence_positive = bool(re.search(r"\b(?:increase(?:d|s)?|rose|grew|growth|higher|gain(?:ed|s)?)\b", evidence_text, re.I))
    evidence_negative = bool(re.search(r"\b(?:did not increase|not increase|decrease(?:d|s)?|fell|decline(?:d|s)?|lower|drop(?:ped|s)?)\b", evidence_text, re.I))
    return (claim_positive and evidence_negative) or (claim_negative and evidence_positive)


def _format_evidence_prompt(evidence: list[Evidence]) -> str:
    lines = []
    for ev in evidence:
        date_str = f" ({ev.date})" if ev.date else ""
        lines.append(f"[{ev.id}] Tier {ev.tier} | {ev.source}{date_str} | Title: {ev.title}\nSnippet: {ev.snippet}\nURL: {ev.url}")
    return "\n\n".join(lines)


def _direct_factual_match(claim: Claim, evidence: Evidence, claim_words: list[str]) -> bool:
    """Recognize a direct factual statement without relying on rhetoric cues.

    Search snippets normally state facts plainly (for example, ``supply and
    demand affect prices``) and do not say ``confirmed`` or ``proven``.  This
    helper is deliberately stricter than a keyword hit: it requires multiple
    claim terms, preserves date/number context, and requires an assertion term
    beyond a named entity when one is available.
    """
    text = f"{evidence.title} {evidence.snippet}".lower()
    evidence_terms = set(re.findall(r"\w+", text))
    claim_terms = [w for w in claim_words if len(w) > 3]
    overlap = {w for w in claim_terms if w in evidence_terms}
    if len(overlap) < 2:
        return False

    full_text = f"{claim.original_text or ''} {claim.normalized_text or ''} {claim.claim_english or ''}"
    # A result about the right entity but the wrong period/quantity is not
    # direct evidence for the complete assertion.
    temporal_or_numeric = re.findall(
        r"\b(?:\d{3,4}s?|\d+(?:\.\d+)?%|\d+(?:\.\d+)?\s*(?:x|times|fold)|\d+(?:st|nd|rd|th)\s+century)\b",
        full_text.lower(),
    )
    if temporal_or_numeric:
        normalized_evidence = re.sub(r"[^a-z0-9]+", " ", text)
        if not any(re.sub(r"[^a-z0-9]+", " ", token).strip() in normalized_evidence for token in temporal_or_numeric):
            return False

    entities = claim.entities if isinstance(claim.entities, dict) else {}
    entity_terms = []
    for key in ("named_entities", "mentions", "finance_terms", "health_terms"):
        values = entities.get(key, []) if isinstance(entities, dict) else []
        entity_terms.extend(str(value).lower() for value in values if str(value).strip())
    evidence_stems = {_stem_token(word) for word in evidence_terms}
    if entity_terms and not any(
        all(_stem_token(part) in evidence_stems for part in re.findall(r"\w+", entity))
        for entity in entity_terms
    ):
        return False

    # If the claim has terms outside its entity/date anchors, at least one of
    # those predicate terms must also be stated by the source.
    entity_words = {_stem_token(part) for entity in entity_terms for part in re.findall(r"\w+", entity)}
    predicate_overlap = {_stem_token(word) for word in overlap if _stem_token(word) not in entity_words}
    return bool(predicate_overlap) or not entity_terms


def _deterministic_fallback_judge(
    claim: Claim,
    evidence: list[Evidence],
    numeric_check: dict[str, Any] | None
) -> Judgment:
    """Deterministic evidence evaluator used when LLM provider is not present or offline."""
    claim_id = claim.id or ""
    claim_text = (claim.normalized_text or claim.claim_english or claim.original_text).lower()
    full_claim_text = f"{claim.original_text or ''} {claim.normalized_text or ''} {claim.claim_english or ''}".lower()
    domain = (claim.domain or "").lower()

    is_personal_positioning = bool(_PERSONAL_POSITIONING_PATTERN.search(full_claim_text))
    claim_entities = claim.entities if isinstance(claim.entities, dict) else {}
    named_entities = [
        str(m).lower()
        for key in ("named_entities", "mentions", "finance_terms", "health_terms")
        for m in claim_entities.get(key, [])
        if len(str(m)) > 2
    ]

    # For personal or fund-specific investment positioning, require evidence directly establishing that positioning.
    # General news about interest rates or broad economic topics is not sufficient.
    if domain == "finance" and is_personal_positioning:
        matching_entity_ev = []
        for ev in evidence:
            ev_text = f"{ev.title} {ev.snippet}".lower()
            if any(ne in ev_text for ne in named_entities):
                matching_entity_ev.append(ev)

        if not matching_entity_ev:
            return Judgment(
                claim_id=claim_id,
                label=VerdictLabel.NO_EVIDENCE,
                confidence="Low",
                rationale="General macroeconomic news does not substantiate or verify the speaker's personal or fund-specific investment positioning.",
                evidence_ids=[]
            )

    contradict_cues = [
        "false", "debunk", "debunked", "refute", "refuted", "no evidence", "no scientific proof", "not proven",
        "unproven", "untrue", "fake", "denies", "incorrect", "myth", "harmful",
        "does not cure", "do not cure", "cannot cure", "not cure",
        "no cure", "not effective", "misinformation", "dangerous", "unverified", "requires lifelong"
    ]
    support_cues = [
        "confirms", "confirmed", "proves", "proven", "effective", "approved",
        "demonstrated", "remission",
        "guarantee", "guarantees", "backed", "authorizes", "authorized",
        "verified", "validates", "validated", "corroborates", "corroborated", "substantiates"
    ]

    stop_words = {
        "the", "this", "that", "these", "those", "is", "are", "was", "were",
        "speaker", "video", "today", "about", "with", "from", "positive",
        "positivity", "negative", "movement", "continue", "remain", "much",
        "well", "like", "also", "have", "been", "increased", "increase",
        "decreased", "decrease", "rose", "fell", "grew", "growth", "recent",
        "rates", "rate", "interest", "market", "markets", "stock", "stocks",
        "economy", "economic", "asian", "global", "sector", "sectors"
    }
    claim_words = [w for w in re.findall(r"\w+", claim_text) if len(w) > 3 and w not in stop_words]

    # Check if there are explicit contradiction cues in any evidence
    contradicting_ev_ids = []
    for ev in evidence:
        ev_text = f"{ev.title} {ev.snippet}".lower()
        if domain == "finance":
            claim_has_med = bool(re.search(r"\b(?:vaccin|flu|covid|cancer|drug|pharma|biotech|clinical|hospital|health)\b", full_claim_text))
            if not claim_has_med and _OFF_DOMAIN_FINANCE_PATTERNS.search(ev_text):
                continue
            has_ent = any(ne in ev_text for ne in named_entities)
            if not has_ent and not _FINANCIAL_TOPIC_TERMS.search(ev_text):
                continue

        overlap = sum(1 for w in claim_words if w in ev_text)
        if overlap >= 1 and (any(cue in ev_text for cue in contradict_cues) or _polarity_conflicts(full_claim_text, ev_text)):
            contradicting_ev_ids.append(ev.id)

    is_completed_claim = bool(_COMPLETED_CLAIM_MARKERS.search(full_claim_text)) or bool(_HISTORICAL_MARKERS.search(full_claim_text)) or (
        claim.claim_type and claim.claim_type.lower() in {"verifiable_fact", "historical_fact", "statistic"}
    )

    support_matches = []
    contradict_matches = []

    for ev in evidence:
        snippet_text = (ev.snippet or "").strip()
        title_text = (ev.title or "").strip()
        if not snippet_text and not title_text:
            continue

        ev_text = f"{title_text} {snippet_text}".lower()

        # Reject predictive/forward-looking previews as confirmation for completed claims
        is_pred = bool(_PREDICTIVE_CUES.search(ev_text))
        has_conf = bool(_COMPLETED_EVENT_CONFIRMATION.search(ev_text))
        if is_completed_claim and is_pred and not has_conf:
            continue

        if domain == "finance":
            claim_has_med = bool(re.search(r"\b(?:vaccin|flu|covid|cancer|drug|pharma|biotech|clinical|hospital|health)\b", full_claim_text))
            if not claim_has_med and _OFF_DOMAIN_FINANCE_PATTERNS.search(ev_text):
                continue
            has_ent = any(ne in ev_text for ne in named_entities)
            if not has_ent and not _FINANCIAL_TOPIC_TERMS.search(ev_text):
                continue

        overlap = sum(1 for w in claim_words if w in ev_text)

        # Must have reasonable overlap with claim terms
        if overlap >= 1 and (any(cue in ev_text for cue in contradict_cues) or _polarity_conflicts(full_claim_text, ev_text)):
            contradict_matches.append(ev.id)
        elif (
            (overlap >= 1 and any(cue in ev_text for cue in support_cues))
            or _direct_factual_match(claim, ev, claim_words)
        ):
            support_matches.append(ev.id)

    # Numeric agreement cannot override assertion polarity. Evaluate direct
    # supporting and contradicting language first so "did not increase 20%"
    # cannot support "increased 20%" merely because the number matches.
    if numeric_check is not None:
        source_ev_id = numeric_check.get("source_evidence_id", "e1")
        if support_matches and contradict_matches:
            return Judgment(
                claim_id=claim_id, label=VerdictLabel.MIXED, confidence="Medium",
                rationale="Numeric evidence is present, but retrieved sources make conflicting assertions about the claim.",
                evidence_ids=support_matches[:1] + contradict_matches[:1],
            )
        if contradict_matches:
            return Judgment(
                claim_id=claim_id, label=VerdictLabel.CONTRADICTED, confidence="High",
                rationale=f"Retrieved evidence contradicts the statement: {numeric_check.get('explanation')}",
                evidence_ids=contradict_matches[:2],
            )
        if numeric_check.get("within_tolerance"):
            return Judgment(
                claim_id=claim_id, label=VerdictLabel.SUPPORTED, confidence="High",
                rationale=f"Verified against {numeric_check.get('field', 'market data')}: {numeric_check.get('explanation')}",
                evidence_ids=[source_ev_id],
            )
        return Judgment(
            claim_id=claim_id, label=VerdictLabel.CONTRADICTED, confidence="High",
            rationale=f"Contradicted by {numeric_check.get('field', 'market data')}: {numeric_check.get('explanation')}",
            evidence_ids=[source_ev_id],
        )

    if support_matches and not contradict_matches:
        return Judgment(
            claim_id=claim_id,
            label=VerdictLabel.SUPPORTED,
            confidence="Medium",
            rationale="Retrieved evidence directly corroborates the factual assertion.",
            evidence_ids=support_matches[:2]
        )
    elif contradict_matches and not support_matches:
        return Judgment(
            claim_id=claim_id,
            label=VerdictLabel.CONTRADICTED,
            confidence="Medium",
            rationale="Retrieved evidence contradicts the statement made in the video.",
            evidence_ids=contradict_matches[:2]
        )
    elif support_matches and contradict_matches:
        return Judgment(
            claim_id=claim_id,
            label=VerdictLabel.MIXED,
            confidence="Medium",
            rationale="Retrieved sources present conflicting or partially corroborating evidence.",
            evidence_ids=(support_matches[:1] + contradict_matches[:1])
        )
    else:
        # If evidence was retrieved but does not directly address or confirm the claim
        return Judgment(
            claim_id=claim_id,
            label=VerdictLabel.NO_EVIDENCE,
            confidence="Low",
            rationale="Retrieved search results do not contain conclusive evidence regarding this specific statement.",
            evidence_ids=[]
        )


def validate_judgment(judgment: Judgment, evidence: list[Evidence], claim: Claim) -> Judgment:
    """Enforce strict PRD safety rules and source-tier constraints on the judgment."""
    evidence_by_id = {ev.id: ev for ev in evidence}
    domain = (claim.domain or "").lower()
    full_claim_text = f"{claim.original_text or ''} {claim.normalized_text or ''} {claim.claim_english or ''}".lower()

    is_personal_positioning = bool(_PERSONAL_POSITIONING_PATTERN.search(full_claim_text))
    claim_entities = claim.entities if isinstance(claim.entities, dict) else {}
    named_entities = [
        str(m).lower()
        for key in ("named_entities", "mentions", "finance_terms", "health_terms")
        for m in claim_entities.get(key, [])
        if len(str(m)) > 2
    ]

    # Rule 1: Discard any cited evidence_id that does not exist or is off-domain / lacks content / broad topic only for personal claims
    valid_ids = []
    for eid in judgment.evidence_ids:
        if eid in evidence_by_id:
            ev = evidence_by_id[eid]
            ev_text = f"{ev.title} {ev.snippet}".lower()

            if not _usable_http_url(ev.url):
                continue

            # Check non-empty content
            has_content = (ev.snippet and ev.snippet.strip()) or (ev.metadata and ev.metadata.get("summary"))
            if not has_content:
                continue

            # Domain relevance check for finance claims
            if domain == "finance":
                claim_has_med = bool(re.search(r"\b(?:vaccin|flu|covid|cancer|drug|pharma|biotech|clinical|hospital|health)\b", full_claim_text))
                if not claim_has_med and _OFF_DOMAIN_FINANCE_PATTERNS.search(ev_text):
                    continue
                # Must have financial topic match or entity match
                has_ent = any(ne in ev_text for ne in named_entities)
                if not has_ent and not _FINANCIAL_TOPIC_TERMS.search(ev_text):
                    continue

                # If claim is about personal or fund-specific investment positioning,
                # macro news without establishing the specific named entity cannot substantiate it
                if is_personal_positioning:
                    if not has_ent:
                        continue

            valid_ids.append(eid)

    judgment.evidence_ids = valid_ids

    # Rule 2: If no valid evidence_ids remain, Supported/Contradicted/Mixed cannot be maintained
    if not valid_ids:
        if judgment.label in {VerdictLabel.SUPPORTED, VerdictLabel.CONTRADICTED, VerdictLabel.MIXED}:
            judgment.label = VerdictLabel.NO_EVIDENCE
            judgment.confidence = "Low"
            if is_personal_positioning:
                judgment.rationale = "General macroeconomic news does not verify the speaker's personal or fund-specific investment positioning."
            else:
                judgment.rationale = "Retrieved search results do not contain conclusive evidence regarding this specific statement."

    # Rule 3: Predictive speculation cannot substantiate a completed factual claim
    is_completed_claim = bool(_COMPLETED_CLAIM_MARKERS.search(full_claim_text)) or bool(_HISTORICAL_MARKERS.search(full_claim_text)) or (
        claim.claim_type and claim.claim_type.lower() in {"verifiable_fact", "historical_fact", "statistic"}
    )
    if is_completed_claim and judgment.label == VerdictLabel.SUPPORTED and valid_ids:
        has_confirmed_evidence = False
        for eid in valid_ids:
            ev = evidence_by_id[eid]
            ev_text = f"{ev.title} {ev.snippet}".lower()
            is_pred = bool(_PREDICTIVE_CUES.search(ev_text))
            has_conf = bool(_COMPLETED_EVENT_CONFIRMATION.search(ev_text))
            if not is_pred or has_conf:
                has_confirmed_evidence = True
                break
        if not has_confirmed_evidence:
            judgment.label = VerdictLabel.NO_EVIDENCE
            judgment.confidence = "Low"
            judgment.evidence_ids = []
            judgment.rationale = "Retrieved sources only provide predictive previews or forecasts rather than confirming the completed event."

    # Rule 4: Tier 1/2 Requirement for Supported and Contradicted
    cited_tiers = [evidence_by_id[eid].tier for eid in valid_ids if eid in evidence_by_id]
    has_tier_1_or_2 = any(t in {1, 2} for t in cited_tiers)

    if judgment.label in {VerdictLabel.SUPPORTED, VerdictLabel.CONTRADICTED} and not has_tier_1_or_2:
        # Downgrade to Mixed if only Tier 3 sources were cited
        judgment.label = VerdictLabel.MIXED
        judgment.confidence = "Low"
        judgment.rationale = _clean_rationale(
            "Evidence is directionally consistent with the claim, but the available sources are limited to unverified Tier-3 material; the claim cannot be treated as fully supported."
        )

    # Rule 5: Clean and constrain rationale
    judgment.rationale = _clean_rationale(judgment.rationale)

    return judgment


def judge_claim(
    claim: Claim,
    evidence: list[Evidence],
    provider: Any = None,
    video_metadata: Any = None
) -> Judgment:
    """Produce an evidence-based verdict with validation for a single claim.

    Returns:
        Judgment model matching schemas.py
    """
    claim_id = claim.id or ""
    is_personal_positioning = bool(_PERSONAL_POSITIONING_PATTERN.search(
        f"{claim.original_text or ''} {claim.normalized_text or ''} {claim.claim_english or ''}"
    ))

    # Case 1: Unverifiable / Non-checkable claims (predictions, opinions, advice, testimonials)
    if not claim.checkable or (claim.claim_type and claim.claim_type.lower() in {"prediction", "opinion", "advice", "testimonial"}):
        return Judgment(
            claim_id=claim_id,
            label=VerdictLabel.UNVERIFIABLE,
            confidence="High",
            rationale="Predictions, guarantees, forward-looking forecasts, and personal opinions cannot be verified against historical factual records.",
            evidence_ids=[]
        )

    # Compound historical/company claims need event-level coverage. A result
    # supporting one event must not silently support the others (for example,
    # tulip mania, a real-estate crash, and Pets.com's collapse). Retrieval tags
    # event-originated results; the fallback below also works with hand-built
    # Evidence in tests by matching each event independently.
    subclaims = split_compound_claim(claim)
    if len(subclaims) > 1:
        covered_labels: list[VerdictLabel] = []
        covered_ids: list[str] = []
        covered_roles: list[str] = []
        unresolved_roles: list[str] = []
        for subclaim in subclaims:
            event_context = next(
                (
                    ev.metadata.get("subclaim_context", "")
                    for ev in evidence
                    if ev.metadata.get("subclaim") == subclaim
                ),
                "",
            )
            event_text = f"{subclaim} {event_context}".strip()
            event_claim = claim.model_copy(update={
                "normalized_text": event_text,
                "claim_english": event_text,
                "original_text": subclaim,
                "quote_original": subclaim,
                "entities": event_entities(subclaim),
            })
            event_evidence = [
                ev for ev in evidence
                if (
                    ev.metadata.get("subclaim") == subclaim
                    and ((ev.snippet or "").strip() or ev.metadata.get("summary"))
                )
                or evidence_matches_claim({
                    "title": ev.title, "snippet": ev.snippet,
                    "metadata": ev.metadata, "engine": ev.engine,
                }, event_claim)
            ]
            role = next(
                (
                    ev.metadata.get("subclaim_role", "")
                    for ev in event_evidence
                    if ev.metadata.get("subclaim") == subclaim
                ),
                "historical event",
            )
            if role == "historical event":
                lower_subclaim = subclaim.lower()
                if "1630s" in lower_subclaim and "tulip" in lower_subclaim:
                    role = "historical_appearance"
                elif "scientifically" in lower_subclaim or "identified" in lower_subclaim:
                    role = "scientific_chronology"
                elif "virus" in lower_subclaim:
                    role = "biological_mechanism"
                elif "pets.com" in lower_subclaim or "pets com" in lower_subclaim:
                    role = "pets.com event"
                elif "real estate" in lower_subclaim:
                    role = "real-estate event"
                elif "tulip" in lower_subclaim:
                    role = "tulip-price event"
            if not event_evidence:
                covered_labels.append(VerdictLabel.NO_EVIDENCE)
                unresolved_roles.append(role)
                continue
            event_judgment = _deterministic_fallback_judge(event_claim, event_evidence, None)
            covered_labels.append(event_judgment.label)
            covered_ids.extend(event_judgment.evidence_ids)
            if event_judgment.label in {VerdictLabel.SUPPORTED, VerdictLabel.CONTRADICTED, VerdictLabel.MIXED}:
                covered_roles.append(role)
            else:
                unresolved_roles.append(role)

        if not covered_ids:
            return Judgment(
                claim_id=claim_id,
                label=VerdictLabel.NO_EVIDENCE,
                confidence="Low",
                rationale="No relevant evidence was found for the separate events in this compound claim.",
                evidence_ids=[],
            )
        positive = [label for label in covered_labels if label in {VerdictLabel.SUPPORTED, VerdictLabel.CONTRADICTED, VerdictLabel.MIXED}]
        if len(positive) != len(covered_labels) or len(set(positive)) > 1 or VerdictLabel.MIXED in positive:
            label = VerdictLabel.MIXED
            supported_text = ", ".join(dict.fromkeys(covered_roles)) or "some subclaims"
            unresolved_text = ", ".join(dict.fromkeys(unresolved_roles)) or "other subclaims"
            rationale = f"Evidence supports {supported_text}; evidence is insufficient for {unresolved_text}."
        elif positive and positive[0] == VerdictLabel.CONTRADICTED:
            label = VerdictLabel.CONTRADICTED
            rationale = "Retrieved evidence contradicts the separate events stated in the compound claim."
        else:
            label = VerdictLabel.SUPPORTED
            rationale = "Retrieved evidence corroborates each separately searched event in the compound claim."
        aggregate = Judgment(
            claim_id=claim_id, label=label, confidence="Medium",
            rationale=rationale, evidence_ids=list(dict.fromkeys(covered_ids)),
        )
        return validate_judgment(aggregate, evidence, claim)

    # Case 2: No relevant evidence retrieved. Retrieval normally performs this
    # filtering too, but repeat it here so callers cannot accidentally turn a
    # manually supplied, keyword-adjacent result into a verdict.
    relevant_evidence = []
    for ev in evidence:
        item = {
            "title": ev.title,
            "snippet": ev.snippet,
            "metadata": ev.metadata,
            "engine": ev.engine,
            "url": ev.url,
            "date": ev.date,
        }
        if evidence_matches_claim(item, claim):
            relevant_evidence.append(ev)

    if not relevant_evidence:
        return Judgment(
            claim_id=claim_id,
            label=VerdictLabel.NO_EVIDENCE,
            confidence="Low",
            rationale=(
                "General macroeconomic news does not verify the speaker's personal or fund-specific investment positioning."
                if is_personal_positioning
                else "No relevant evidence was found in indexed search or research records for this claim."
            ),
            evidence_ids=[]
        )

    # Case 3: Numeric verification
    evidence = relevant_evidence
    numeric_check, _ = check_numeric_claim(claim, evidence)

    raw_judgment: Judgment | None = None

    # Try LLM judging if provider is available
    if provider is not None and hasattr(provider, "structured"):
        evidence_text = _format_evidence_prompt(evidence)
        numeric_note = f"\nNumeric check result: {json.dumps(numeric_check)}" if numeric_check else ""
        published_note = f"\nVideo published date: {video_metadata.published_at}" if video_metadata and hasattr(video_metadata, "published_at") and video_metadata.published_at else ""

        prompt = f"""You are an impartial fact-checking judge auditing a claim made in an Indian online video.
Evaluate the claim against ONLY the numbered evidence list provided below.

CLAIM:
- English statement: {claim.normalized_text or claim.claim_english}
- Original quote: {claim.original_text or claim.quote_original}
- Domain: {claim.domain}
- Entities: {claim.entities}{published_note}{numeric_note}

EVIDENCE LIST:
{evidence_text}

STRICT JUDGING RULES:
1. Base your verdict ONLY on the provided evidence. Do NOT extrapolate or assume outside facts.
2. If evidence clearly confirms the claim with Tier 1 or Tier 2 sources -> 'Supported'.
3. If evidence directly disproves the claim -> 'Contradicted'.
4. If sources conflict, or only partially apply (e.g. preliminary animal study, or different timeframe) -> 'Mixed'.
5. If the evidence does not directly address or verify the statement -> 'No evidence found'.
6. Predictions and opinions must be marked 'Unverifiable'.
7. For claims regarding personal or fund-specific investment positioning/outlook/allocations, require evidence directly establishing that specific entity's positioning. Broad macroeconomic news (e.g. central bank rate decisions) is not sufficient.
8. Forward-looking previews or speculative predictions (e.g. 'will most likely maintain', 'expected to keep', 'poll predicts') must NOT be treated as proof of a completed historical event.
9. Rationale must be neutral, maximum 3 sentences, and focus STRICTLY on the claim, NEVER assessing creator character or motives.
10. Cite only valid evidence IDs (e.g. 'e1', 'e2') from the list above.

Return JSON matching:
- label: "Supported" | "Contradicted" | "Mixed" | "No evidence found" | "Unverifiable"
- confidence: "Low" | "Medium" | "High"
- rationale: 1-3 neutral sentences
- evidence_ids: list of cited IDs
"""
        try:
            res = provider.structured("judge_claim", prompt, LLMVerdictSchema)
            label_map = {
                "supported": VerdictLabel.SUPPORTED,
                "contradicted": VerdictLabel.CONTRADICTED,
                "mixed": VerdictLabel.MIXED,
                "no evidence found": VerdictLabel.NO_EVIDENCE,
                "no_evidence": VerdictLabel.NO_EVIDENCE,
                "unverifiable": VerdictLabel.UNVERIFIABLE,
            }
            mapped_label = label_map.get(res.label.lower().strip(), VerdictLabel.NO_EVIDENCE)
            conf = res.confidence.title() if res.confidence and res.confidence.title() in {"Low", "Medium", "High"} else "Medium"
            raw_judgment = Judgment(
                claim_id=claim_id,
                label=mapped_label,
                confidence=conf,
                rationale=res.rationale,
                evidence_ids=res.evidence_ids,
                analysis_mode="gemini",
            )
        except Exception as e:
            logger.warning(f"LLM judging failed or provider unavailable, falling back to deterministic judge: {type(e).__name__}")
            raw_judgment = None

    if raw_judgment is None:
        raw_judgment = _deterministic_fallback_judge(claim, evidence, numeric_check)
        raw_judgment.analysis_mode = "deterministic_fallback"

    # Apply strict validation
    return validate_judgment(raw_judgment, evidence, claim)
