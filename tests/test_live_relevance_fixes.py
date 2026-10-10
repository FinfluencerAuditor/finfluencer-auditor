"""Regression tests for live financial evidence retrieval relevance, domain filtering, and ranking."""

from unittest.mock import Mock
import pytest
from app.judge import judge_claim, validate_judgment
from app.numeric import check_numeric_claim
from app.retrieve import (
    compute_claim_relevance,
    draft_queries,
    retrieve_claim,
)
from app.schemas import Claim, Evidence, VerdictLabel


def test_financial_claim_filters_irrelevant_medical_results():
    """A financial claim about interest rates or market sentiment must reject medical/COVID/HER2 search results."""
    claim = Claim(
        id="c1",
        original_text="We have been positive on Indian markets with recent interest rate movements.",
        normalized_text="We have been positive on Indian markets with recent interest rate movements.",
        start_seconds=10.0,
        domain="finance",
        entities={"finance_terms": ["interest rate", "markets"]},
        checkable=True
    )
    mock_serp = Mock()
    mock_serp.search.return_value = {
        "organic_results": [
            {
                "title": "HER2-Positive Breast Cancer Treatment Guidelines",
                "link": "https://www.cancer.gov/types/breast/her2-positive",
                "source": "National Cancer Institute",
                "snippet": "Patients with HER2-positive disease showed positive response to targeted antibody therapy."
            },
            {
                "title": "COVID-19 Positive Cases and Testing Guidance",
                "link": "https://www.hawaii.edu/covid19/aloha-update",
                "source": "University of Hawaii",
                "snippet": "Individuals who tested positive for COVID-19 should remain in isolation."
            },
            {
                "title": "RBI Interest Rate Decision and Market Outlook",
                "link": "https://www.reuters.com/markets/asia/rbi-rates-outlook",
                "source": "Reuters",
                "snippet": "Analysts remain positive on Indian equities following the latest RBI interest rate policy."
            }
        ]
    }
    evidence, status = retrieve_claim(claim, mock_serp)
    assert status == "complete"
    # Only the relevant Reuters financial article should be retained
    assert len(evidence) == 1
    assert "reuters.com" in evidence[0].url
    assert "HER2" not in evidence[0].title
    assert "COVID" not in evidence[0].title


def test_financial_claim_filters_empty_snippet_tier_1_results():
    """A Tier-1 result with an empty snippet must NOT be accepted as evidence."""
    claim = Claim(
        id="c2",
        original_text="Manufacturing sector allocation increased across auto and metals.",
        normalized_text="Manufacturing sector allocation increased across auto and metals.",
        start_seconds=20.0,
        domain="finance",
        entities={"finance_terms": ["manufacturing", "allocation"]},
        checkable=True
    )
    mock_serp = Mock()
    mock_serp.search.return_value = {
        "organic_results": [
            # Tier 1 with empty snippet
            {
                "title": "Census Bureau Manufacturing Report",
                "link": "https://www.census.gov/library/stories/older-workers.html",
                "source": "Census.gov",
                "snippet": ""
            },
            # Tier 2 with relevant snippet
            {
                "title": "Auto and Metals Lead Manufacturing Growth in India",
                "link": "https://www.moneycontrol.com/news/business/manufacturing-growth.html",
                "source": "Moneycontrol",
                "snippet": "Investment in auto and metal manufacturing segments rose significantly this quarter."
            }
        ]
    }
    evidence, status = retrieve_claim(claim, mock_serp)
    assert status == "complete"
    assert len(evidence) == 1
    assert evidence[0].source == "Moneycontrol"
    assert evidence[0].snippet != ""


def test_relevant_lower_tier_evidence_outranks_irrelevant_higher_tier():
    """Relevance must be evaluated before source tier so that relevant news outranks generic government overviews."""
    claim = Claim(
        id="c3",
        original_text="Tata Motors quarterly profit surged 15%.",
        normalized_text="Tata Motors quarterly profit surged 15%.",
        start_seconds=30.0,
        domain="finance",
        entities={"named_entities": ["Tata Motors"], "finance_terms": ["profit"]},
        numeric_info=[{"original": "15%"}]
    )
    mock_serp = Mock()
    mock_serp.search.return_value = {
        "organic_results": [
            # Tier 1 (CDC / Gov) - weak relevance
            {
                "title": "CDC General Enterprise Report",
                "link": "https://www.cdc.gov/flu/overview",
                "source": "CDC",
                "snippet": "General enterprise guidelines across organizations."
            },
            # Tier 2 (Reuters) - highly relevant with exact entity and numbers
            {
                "title": "Tata Motors Q3 profit surges 15%",
                "link": "https://www.reuters.com/business/autos/tata-motors-profit",
                "source": "Reuters",
                "snippet": "Tata Motors reported a 15% surge in quarterly net profit driven by commercial vehicles."
            }
        ]
    }
    evidence, status = retrieve_claim(claim, mock_serp)
    assert status == "complete"
    assert len(evidence) >= 1
    # Top ranked evidence must be the highly relevant Reuters article
    assert evidence[0].id == "e1"
    assert "Tata Motors" in evidence[0].title
    assert "reuters.com" in evidence[0].url


def test_historical_financial_claim_vs_current_quote():
    """A historical claim for a past period must not be matched against current real-time market quotes."""
    historical_claim = Claim(
        id="c4",
        original_text="Nifty 50 was at 18000 in 2022.",
        normalized_text="Nifty 50 was at 18000 in 2022.",
        start_seconds=0.0,
        domain="finance",
        checkable=True,
        numeric_info=[{"original": "18000"}]
    )
    # Current Google Finance real-time quote (no historical date context)
    current_evidence = [
        Evidence(
            id="e1",
            engine="google_finance",
            title="NIFTY 50 (INDEXNSE: NIFTY_50)",
            source="Google Finance",
            tier=1,
            snippet="Price: 24,850.00; Previous Close: 24,800.00",
            url="https://www.google.com/finance",
            metadata={"summary": {"price": "24,850.00", "previous_close": "18,000.00"}}
        )
    ]
    numeric_check, status = check_numeric_claim(historical_claim, current_evidence)
    # Because it is a historical claim ('in 2022'), real-time undated quotes must not match
    assert numeric_check is None


def test_private_portfolio_allocation_no_evidence():
    """Private fund house positioning claims without official public records return No evidence found."""
    claim = Claim(
        id="c5",
        original_text="We have overweight exposure on healthcare services at this point in time.",
        normalized_text="Our fund maintains an overweight allocation to healthcare services.",
        start_seconds=45.0,
        domain="finance",
        checkable=True
    )
    # Search returns generic healthcare overviews
    evidence = [
        Evidence(
            id="e1",
            engine="google",
            title="Healthcare Services Industry Trends 2024",
            source="deloitte.com",
            tier=2,
            snippet="The global healthcare services sector is expected to expand rapidly.",
            url="https://deloitte.com/healthcare"
        )
    ]
    judgment = judge_claim(claim, evidence)
    assert judgment.label == VerdictLabel.NO_EVIDENCE
    assert judgment.evidence_ids == []
