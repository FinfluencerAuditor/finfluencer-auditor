"""Regression and quality improvement tests for claim extraction, retrieval, and judging."""

from unittest.mock import Mock
import pytest
from app.extract import extract_claims, _is_meaningful, _align_claim
from app.judge import judge_claim, validate_judgment
from app.retrieve import draft_queries, retrieve_claim
from app.schemas import Claim, Evidence, Judgment, TranscriptSegment, VerdictLabel


def test_interview_questions_and_greetings_excluded_or_uncheckable():
    # 1. Conversational greetings
    greeting_claim = Claim(
        original_text="Hello everyone, welcome back to the channel, don't forget to like and subscribe.",
        normalized_text="Hello everyone, welcome back to the channel, don't forget to like and subscribe.",
        start_seconds=0.0,
        end_seconds=5.0
    )
    assert not _is_meaningful(greeting_claim)

    # 2. Pure interview question
    question_claim = Claim(
        original_text="What do you think about the market valuation today?",
        normalized_text="What do you think about the market valuation today?",
        start_seconds=10.0,
        end_seconds=15.0
    )
    assert not _is_meaningful(question_claim)

    # 3. Aligned question marked as opinion/uncheckable
    aligned = _align_claim(question_claim, [])
    assert aligned.checkable is False
    assert aligned.claim_type == "opinion"


def test_finance_query_generation_focused_and_no_filler():
    claim = Claim(
        id="c1",
        original_text="Speaker says in this video portfolio today Tata Motors Q3 profit rose 15%",
        normalized_text="Tata Motors Q3 net profit increased by 15%",
        start_seconds=10.0,
        domain="finance",
        entities={"named_entities": ["Tata Motors"], "finance_terms": ["profit"]},
        numeric_info=[{"original": "15%"}]
    )
    queries = draft_queries(claim)
    assert len(queries) <= 3
    for q in queries:
        query_str = str(q.get("q", "")).lower()
        # Verify filler is not dominating the query
        assert "speaker" not in query_str
        assert "portfolio" not in query_str
        assert "video" not in query_str
        # Verify key entity is present
        assert "tata" in query_str or "profit" in query_str


def test_retrieval_filters_empty_snippets_and_unrelated_domains():
    claim = Claim(
        id="c1",
        original_text="Ola Electric IPO valuation is estimated at 38000 crore.",
        normalized_text="Ola Electric IPO valuation is estimated at 38000 crore.",
        start_seconds=0.0,
        domain="finance",
        entities={"named_entities": ["Ola Electric"]}
    )

    mock_serp = Mock()
    mock_serp.search.return_value = {
        "organic_results": [
            # Item 1: Valid Tier 2 news with snippet
            {
                "title": "Ola Electric IPO Valuation Target",
                "link": "https://www.reuters.com/business/ola-electric-ipo",
                "source": "Reuters",
                "snippet": "Ola Electric aims for a valuation of around 38000 crore in upcoming IPO."
            },
            # Item 2: Unrelated watch domain
            {
                "title": "Luxury Watches Valuation Guide",
                "link": "https://www.chrono24.com/magazine/watches-valuation",
                "source": "Chrono24",
                "snippet": "Valuation of luxury vintage watches in 2024."
            },
            # Item 3: Empty snippet on Tier 3 site
            {
                "title": "Random Blog Post",
                "link": "https://randomblog123.com/post",
                "source": "Random Blog",
                "snippet": ""
            },
            # Item 4: University course syllabus
            {
                "title": "Finance 101 Syllabus",
                "link": "https://mit.edu/courses/finance101",
                "source": "MIT",
                "snippet": "Course syllabus on portfolio theory and corporate finance."
            }
        ]
    }

    evidence_list, status = retrieve_claim(claim, mock_serp)
    assert status == "complete"
    # Should only retain the relevant Reuters article
    urls = [e.url for e in evidence_list]
    assert "https://www.reuters.com/business/ola-electric-ipo" in urls
    assert not any("chrono24.com" in u for u in urls)
    assert not any("mit.edu" in u for u in urls)
    assert not any(e.snippet == "" for e in evidence_list)


def test_unsupported_claim_not_labelled_supported():
    claim = Claim(
        id="c1",
        original_text="Company XYZ will acquire ABC next week for 500 crore.",
        normalized_text="Company XYZ will acquire ABC next week for 500 crore.",
        start_seconds=0.0,
        domain="finance",
        checkable=True
    )
    # Evidence is on a completely different topic but shares 2-3 generic words
    evidence = [
        Evidence(
            id="e1",
            engine="google",
            title="General Market Overview XYZ",
            source="reuters.com",
            tier=2,
            snippet="The market traded sideways this week with little movement in index funds.",
            url="https://reuters.com/market"
        )
    ]
    judgment = judge_claim(claim, evidence)
    # Must NOT be Supported
    assert judgment.label == VerdictLabel.NO_EVIDENCE


def test_missing_evidence_not_labelled_contradicted():
    claim = Claim(
        id="c2",
        original_text="New fintech startup launched a zero fee account.",
        normalized_text="New fintech startup launched a zero fee account.",
        start_seconds=0.0,
        domain="finance",
        checkable=True
    )
    # Empty evidence list
    judgment = judge_claim(claim, [])
    assert judgment.label == VerdictLabel.NO_EVIDENCE
    assert judgment.label != VerdictLabel.CONTRADICTED


def test_tier_3_evidence_cannot_establish_supported():
    claim = Claim(
        id="c3",
        original_text="Stock ABC announced 50% dividend.",
        normalized_text="Stock ABC announced 50% dividend.",
        start_seconds=0.0,
        domain="finance",
        checkable=True
    )
    tier3_evidence = [
        Evidence(
            id="e1",
            engine="google",
            title="Stock ABC Dividend Rumors",
            source="randomblog.net",
            tier=3,
            snippet="Reported that ABC confirms 50% dividend.",
            url="https://randomblog.net/post"
        )
    ]
    judgment = judge_claim(claim, tier3_evidence)
    # Should be downgraded to Mixed or No evidence, not Supported
    assert judgment.label != VerdictLabel.SUPPORTED
