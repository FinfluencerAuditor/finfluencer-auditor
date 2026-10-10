"""Critical regression test: Prevent off-domain grammar quizzes, medical studies, and generic posts from corroborating financial claims."""

from unittest.mock import Mock
import pytest
from app.judge import judge_claim, validate_judgment
from app.retrieve import retrieve_claim, compute_claim_relevance
from app.schemas import Claim, Evidence, Judgment, VerdictLabel


def test_facebook_grammar_quiz_rejected_and_cannot_corroborate_finance_claim():
    """Exact reproduction of live failure: Facebook English grammar quiz sharing 'has increased' cannot support interest rate claim."""
    claim = Claim(
        id="c_rate",
        original_text="we have been positive on continue to remain positive in fact that positivity has increased with the recent interest rate movement",
        normalized_text="Our positive outlook has increased following recent interest rate movements.",
        start_seconds=677.0,
        end_seconds=685.0,
        domain="finance",
        entities={"finance_terms": ["interest rate"]},
        checkable=True
    )

    facebook_item = {
        "title": "The number of students seeking admission ________.",
        "link": "https://www.facebook.com/groups/171634366621752/posts/367447367040450/",
        "source": "Facebook · English for Today",
        "snippet": "The number of students seeking admission ______. 1) has increased 2) have increased..."
    }

    mock_serp = Mock()
    mock_serp.search.return_value = {"organic_results": [facebook_item]}

    # 1. Retrieval gate: Must reject the grammar quiz
    evidence_list, status = retrieve_claim(claim, mock_serp)
    assert status == "complete"
    assert len(evidence_list) == 0

    # 2. Judge gate: Even if an irrelevant item were manually passed to judge, it must NOT yield Supported or Mixed
    irrelevant_evidence = [
        Evidence(
            id="e1",
            engine="google",
            title=facebook_item["title"],
            source=facebook_item["source"],
            tier=3,
            snippet=facebook_item["snippet"],
            url=facebook_item["link"]
        )
    ]
    judgment = judge_claim(claim, irrelevant_evidence)
    assert judgment.label == VerdictLabel.NO_EVIDENCE
    assert judgment.evidence_ids == []
    assert judgment.confidence == "Low"


def test_medical_study_cannot_corroborate_interest_rate_claim():
    """A medical study about HER2 positive cancer must be rejected by both retrieval and judge for a finance claim."""
    claim = Claim(
        id="c_rate2",
        original_text="we have been positive on continue to remain positive with recent interest rate movement",
        normalized_text="We have a positive outlook with recent interest rate movements.",
        start_seconds=677.0,
        domain="finance",
        entities={"finance_terms": ["interest rate"]},
        checkable=True
    )
    med_evidence = [
        Evidence(
            id="e1",
            engine="google",
            title="HER2 Positive Breast Cancer Clinical Study",
            source="NIH / NCI",
            tier=1,
            snippet="Patients showed positive response to targeted antibody therapy after dosage was increased.",
            url="https://cancer.gov/her2-positive"
        )
    ]
    judgment = judge_claim(claim, med_evidence)
    assert judgment.label == VerdictLabel.NO_EVIDENCE
    assert judgment.evidence_ids == []


def test_generic_manufacturing_overview_cannot_support_private_fund_positioning():
    """Generic industry taxonomy pages cannot corroborate private fund sector allocation claims."""
    claim = Claim(
        id="c_alloc",
        original_text="we have overweight exposure on manufacturing and auto metals",
        normalized_text="Our portfolio maintains overweight exposure to manufacturing and auto metals.",
        start_seconds=700.0,
        domain="finance",
        checkable=True
    )
    generic_evidence = [
        Evidence(
            id="e1",
            engine="google",
            title="Manufacturing Sector - an overview",
            source="ScienceDirect.com",
            tier=1,
            snippet="The critical manufacturing sector includes auto, metals, and cement.",
            url="https://sciencedirect.com/manufacturing"
        )
    ]
    judgment = judge_claim(claim, generic_evidence)
    assert judgment.label == VerdictLabel.NO_EVIDENCE
    assert judgment.evidence_ids == []


def test_interest_rate_news_cannot_support_personal_positivity_claim():
    """Exact reproduction of live failure: BBC rate hold and RBA rate hike news cannot substantiate speaker's personal positivity claim."""
    claim = Claim(
        id="c_positivity",
        original_text="We have been positive … that positivity has increased with the recent interest rate movement.",
        normalized_text="We have been positive and that positivity has increased with the recent interest rate movement.",
        start_seconds=677.0,
        end_seconds=685.0,
        domain="finance",
        entities={"finance_terms": ["interest rate"]},
        checkable=True
    )

    macro_evidence = [
        Evidence(
            id="e1",
            engine="google_news",
            title="US holds interest rates steady in first since 2022",
            source="BBC",
            tier=2,
            snippet="US holds interest rates steady in first pause since 2022 after multiple rate hikes.",
            url="https://www.bbc.com/news/business-interest-rates"
        ),
        Evidence(
            id="e2",
            engine="google",
            title="Reserve Bank hikes cash rate to 4.1 per cent in a split decision",
            source="YouTube",
            tier=3,
            snippet="Reserve Bank hikes cash rate to 4.1 per cent in a split decision amid persistent inflation.",
            url="https://www.youtube.com/watch?v=rates-update"
        )
    ]

    judgment = judge_claim(claim, macro_evidence)
    assert judgment.label == VerdictLabel.NO_EVIDENCE
    assert judgment.evidence_ids == []
    assert judgment.confidence == "Low"
    assert "does not" in judgment.rationale or "unsupported" in judgment.rationale or "conclusive" in judgment.rationale


def test_fund_specific_disclosure_can_support_positioning_when_entity_matches():
    """If official disclosures directly substantiate the named fund's positive stance / allocation, it can be supported."""
    claim = Claim(
        id="c_fund_pos",
        original_text="We have been positive on auto and our fund increased allocation",
        normalized_text="Quantum Mutual Fund maintains a positive stance on auto.",
        start_seconds=100.0,
        domain="finance",
        entities={"named_entities": ["Quantum Mutual Fund"], "finance_terms": ["auto"]},
        checkable=True
    )
    fund_evidence = [
        Evidence(
            id="e1",
            engine="google_news",
            title="Quantum Mutual Fund Monthly Portfolio Disclosure",
            source="reuters.com",
            tier=2,
            snippet="Quantum Mutual Fund confirms positive outlook and increased allocation to the auto sector.",
            url="https://reuters.com/markets/funds/quantum-auto"
        )
    ]
    judgment = judge_claim(claim, fund_evidence)
    assert judgment.label == VerdictLabel.SUPPORTED
    assert "e1" in judgment.evidence_ids
