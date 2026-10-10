"""Dedicated unit and integration tests verifying Google Finance and Google News evidence retrieval."""

from unittest.mock import Mock
import pytest
from app.judge import judge_claim
from app.numeric import check_numeric_claim, values_match
from app.retrieve import (
    draft_queries,
    parse_engine_response,
    retrieve_claim,
    route_claim,
)
from app.schemas import Claim, Evidence, VerdictLabel
from app.serp import SerpApiClient, SerpApiError


# ==========================================
# 1. Google Finance Retrieval & Verification
# ==========================================

def test_google_finance_query_generation():
    """Verify that a concise financial entity routes to google_finance with the clean symbol/name."""
    claim = Claim(
        id="c1",
        original_text="Reliance PE ratio is 26.4 currently.",
        normalized_text="Reliance Industries P/E ratio is 26.4.",
        start_seconds=0.0,
        domain="finance",
        entities={"named_entities": ["RELIANCE"]},
        numeric_info=[{"original": "26.4"}]
    )
    queries = draft_queries(claim)
    assert len(queries) <= 3
    finance_queries = [q for q in queries if q.get("engine") == "google_finance"]
    assert len(finance_queries) >= 1
    assert finance_queries[0]["q"] in {"RELIANCE", "RELIANCE:NSE"}


def test_google_finance_structured_market_data_parsing():
    """Verify that raw Google Finance API responses are parsed into structured Tier-1 Evidence."""
    raw_response = {
        "summary": {
            "title": "Tata Motors Ltd",
            "stock": "TATAMOTORS:NSE",
            "price": "980.50",
            "pe_ratio": "16.2",
            "market_cap": "3.25T",
            "previous_close": "975.00",
            "fifty_two_week_high": "1,179.00",
            "fifty_two_week_low": "600.00"
        },
        "knowledge_graph": {
            "title": "Tata Motors Limited",
            "description": "Tata Motors is an Indian multinational automotive manufacturing company."
        }
    }
    items = parse_engine_response("google_finance", raw_response)
    assert len(items) >= 1
    item = items[0]
    assert item["engine"] == "google_finance"
    assert "Tata Motors" in item["title"]
    assert item["source"] == "Google Finance"
    assert "Price: 980.50" in item["snippet"]
    assert "Pe Ratio: 16.2" in item["snippet"]
    assert item["metadata"]["summary"]["pe_ratio"] == "16.2"


def test_google_finance_numeric_supported_verdict():
    """Verify that a matching P/E claim evaluated against Google Finance structured quote yields Supported."""
    claim = Claim(
        id="c1",
        original_text="Tata Motors P/E ratio stands at 16.2.",
        normalized_text="Tata Motors P/E ratio stands at 16.2.",
        start_seconds=10.0,
        domain="finance",
        checkable=True
    )
    evidence = [
        Evidence(
            id="e1",
            engine="google_finance",
            title="Tata Motors Ltd (TATAMOTORS:NSE)",
            source="Google Finance",
            tier=1,
            snippet="Price: 980.50; Pe Ratio: 16.2; Market Cap: 3.25T",
            url="https://www.google.com/finance",
            metadata={"summary": {"pe_ratio": "16.2", "price": "980.50"}}
        )
    ]
    numeric_check, status = check_numeric_claim(claim, evidence)
    assert status == "complete"
    assert numeric_check["within_tolerance"] is True
    assert numeric_check["diff_pct"] == 0.0

    judgment = judge_claim(claim, evidence)
    assert judgment.label == VerdictLabel.SUPPORTED
    assert judgment.confidence == "High"
    assert "e1" in judgment.evidence_ids


def test_google_finance_numeric_contradicted_verdict():
    """Verify that an exaggerated P/E claim evaluated against Google Finance quote yields Contradicted."""
    claim = Claim(
        id="c2",
        original_text="Tata Motors P/E ratio is over 45.",
        normalized_text="Tata Motors P/E ratio is 45.",
        start_seconds=10.0,
        domain="finance",
        checkable=True
    )
    evidence = [
        Evidence(
            id="e1",
            engine="google_finance",
            title="Tata Motors Ltd (TATAMOTORS:NSE)",
            source="Google Finance",
            tier=1,
            snippet="Price: 980.50; Pe Ratio: 16.2; Market Cap: 3.25T",
            url="https://www.google.com/finance",
            metadata={"summary": {"pe_ratio": "16.2"}}
        )
    ]
    numeric_check, status = check_numeric_claim(claim, evidence)
    assert status == "complete"
    assert numeric_check["within_tolerance"] is False

    judgment = judge_claim(claim, evidence)
    assert judgment.label == VerdictLabel.CONTRADICTED
    assert judgment.confidence == "High"
    assert "e1" in judgment.evidence_ids


# ==========================================
# 2. Google News Retrieval & Verification
# ==========================================

def test_google_news_query_generation():
    """Verify that complex financial claims generate targeted Google News queries with entity and metric."""
    claim = Claim(
        id="c3",
        original_text="HDFC Bank reported net profit growth of 18% in Q3.",
        normalized_text="HDFC Bank reported net profit growth of 18% in Q3.",
        start_seconds=120.0,
        domain="finance",
        entities={"named_entities": ["HDFC Bank"], "finance_terms": ["profit"]},
        numeric_info=[{"original": "18%"}]
    )
    queries = draft_queries(claim)
    news_queries = [q for q in queries if q.get("engine") == "google_news"]
    assert len(news_queries) >= 1
    q_str = news_queries[0]["q"].lower()
    assert "hdfc bank" in q_str
    assert "18%" in q_str or "profit" in q_str


def test_google_news_response_parsing_with_dates():
    """Verify that Google News articles with publication dates and Tier-2 sources are parsed properly."""
    raw_news = {
        "news_results": [
            {
                "title": "HDFC Bank Q3 profit jumps 18% YoY to Rs 16,370 crore",
                "link": "https://www.moneycontrol.com/news/business/earnings/hdfc-bank-q3-results.html",
                "source": {"name": "Moneycontrol"},
                "date": "Jan 16, 2024",
                "snippet": "HDFC Bank on Tuesday reported an 18 percent rise in net profit for the December quarter."
            }
        ]
    }
    items = parse_engine_response("google_news", raw_news)
    assert len(items) == 1
    assert items[0]["title"] == "HDFC Bank Q3 profit jumps 18% YoY to Rs 16,370 crore"
    assert items[0]["source"] == "Moneycontrol"
    assert items[0]["date"] == "Jan 16, 2024"
    assert "18 percent" in items[0]["snippet"]


def test_google_news_corroboration_judging():
    """Verify that non-empty Tier-2 news confirming a financial metric yields Supported."""
    claim = Claim(
        id="c3",
        original_text="HDFC Bank Q3 profit rose 18%.",
        normalized_text="HDFC Bank Q3 profit increased 18%.",
        start_seconds=120.0,
        domain="finance",
        checkable=True
    )
    evidence = [
        Evidence(
            id="e1",
            engine="google_news",
            title="HDFC Bank Q3 net profit rose 18% to ₹16,370 crore",
            source="Moneycontrol",
            tier=2,
            date="Jan 16, 2024",
            snippet="HDFC Bank reported net profit rose 18% during the third quarter.",
            url="https://www.moneycontrol.com/news/business/hdfc-q3.html"
        )
    ]
    judgment = judge_claim(claim, evidence)
    assert judgment.label == VerdictLabel.SUPPORTED
    assert "e1" in judgment.evidence_ids


# ==========================================
# 3. Edge Cases, Failures, and Conflicts
# ==========================================

def test_conflicting_evidence_returns_mixed():
    """Verify that conflicting news reports (one showing rise, one showing drop) yield Mixed verdict."""
    claim = Claim(
        id="c4",
        original_text="Company XYZ sales increased by 20%.",
        normalized_text="Company XYZ sales increased by 20%.",
        start_seconds=50.0,
        domain="finance",
        checkable=True
    )
    evidence = [
        Evidence(
            id="e1",
            engine="google_news",
            title="XYZ sales grew 20% in preliminary report",
            source="Reuters",
            tier=2,
            snippet="Preliminary data confirms Company XYZ sales increased 20%.",
            url="https://reuters.com/xyz-sales"
        ),
        Evidence(
            id="e2",
            engine="google_news",
            title="Auditor refutes XYZ sales numbers",
            source="Bloomberg",
            tier=2,
            snippet="Auditor refutes preliminary statement and reports sales fell.",
            url="https://bloomberg.com/xyz-audit"
        )
    ]
    judgment = judge_claim(claim, evidence)
    assert judgment.label == VerdictLabel.MIXED
    assert len(judgment.evidence_ids) == 2


def test_serp_provider_timeout_safe_fallback():
    """Verify that provider timeouts are handled safely without crashing the pipeline."""
    claim = Claim(
        id="c5",
        original_text="Nifty 50 reached new all-time high.",
        normalized_text="Nifty 50 reached new all-time high.",
        start_seconds=0.0,
        domain="finance",
        checkable=True
    )
    mock_serp = Mock()
    mock_serp.search.side_effect = SerpApiError("SerpApi request failed: HTTP 504 Gateway Timeout")

    evidence, status = retrieve_claim(claim, mock_serp)
    assert status == "failed"
    assert evidence == []


def test_google_finance_price_comparison_grounding_with_date():
    """Verify that Google Finance quotes preserve currency, exchange, and market session date when evaluating numeric claims."""
    claim = Claim(
        id="c_rel_grounding",
        original_text="Reliance is trading around ₹1,170.",
        normalized_text="Reliance is trading around ₹1,170 on the NSE.",
        start_seconds=0,
        domain="finance",
        entities={"named_entities": ["Reliance Industries"]},
        numeric_info=[{"original": "₹1,170", "value": 1170.0, "unit": "currency"}],
        checkable=True
    )
    mock_finance_evidence = [
        Evidence(
            id="e1",
            engine="google_finance",
            title="Reliance Industries Ltd",
            source="Google Finance",
            tier=1,
            date="Oct 09 2026, 03:59:52 PM UTC+05:30",
            snippet="Exchange: NSE; Price: INR1170.9; Extracted Price: 1170.9; Currency: INR; Date: Oct 09 2026, 03:59:52 PM UTC+05:30",
            url="https://www.google.com/finance",
            metadata={"summary": {"price": "INR1170.9", "stock": "RELIANCE:NSE", "date": "Oct 09 2026, 03:59:52 PM UTC+05:30"}}
        )
    ]

    judgment = judge_claim(claim, mock_finance_evidence)
    assert judgment.label == VerdictLabel.SUPPORTED
    assert judgment.confidence == "High"
    assert "e1" in judgment.evidence_ids
    assert "Oct 09 2026" in judgment.rationale
    assert "Google Finance" in judgment.rationale


def test_predictive_news_rejected_for_completed_factual_claim():
    """Verify that forward-looking/predictive news previews are not accepted as proof of completed events."""
    claim = Claim(
        id="case_b_rbi",
        original_text="RBI kept the repo rate unchanged at 6.5% during the monetary policy meeting.",
        normalized_text="RBI kept the repo rate unchanged at 6.5% during the monetary policy meeting.",
        start_seconds=0.0,
        domain="finance",
        claim_type="verifiable_fact",
        entities={"named_entities": ["RBI", "Monetary Policy Committee"], "finance_terms": ["repo rate"]},
        numeric_info=[{"original": "6.5%", "value": 6.5, "unit": "%"}],
        checkable=True
    )
    predictive_evidence = [
        Evidence(
            id="e1",
            engine="google_news",
            title="RBI Monetary Policy: Repo rate outlook ahead of MPC meeting",
            source="Financial Express",
            tier=2,
            date="Dec 4, 2024",
            snippet="The RBI's Monetary Policy Committee will most likely maintain its policy repo rate at 6.5% at its upcoming review meeting.",
            url="https://www.financialexpress.com/policy/economy-rbi-monetary-policy-preview-12345/"
        )
    ]

    # Numeric check should skip predictive preview snippet
    numeric_check, status = check_numeric_claim(claim, predictive_evidence)
    assert numeric_check is None

    # Judge must not mark Supported on predictive evidence alone
    judgment = judge_claim(claim, predictive_evidence)
    assert judgment.label == VerdictLabel.NO_EVIDENCE
    assert judgment.evidence_ids == []
    assert "predictive" in judgment.rationale.lower() or "no relevant evidence" in judgment.rationale.lower() or "search results do not contain conclusive" in judgment.rationale.lower()


def test_confirmed_decision_marks_completed_factual_claim_supported():
    """Verify that confirmed policy resolutions and past-tense reports are accepted as proof for completed event claims."""
    claim = Claim(
        id="case_b_rbi",
        original_text="RBI kept the repo rate unchanged at 6.5% during the monetary policy meeting.",
        normalized_text="RBI kept the repo rate unchanged at 6.5% during the monetary policy meeting.",
        start_seconds=0.0,
        domain="finance",
        claim_type="verifiable_fact",
        entities={"named_entities": ["RBI", "Monetary Policy Committee"], "finance_terms": ["repo rate"]},
        numeric_info=[{"original": "6.5%", "value": 6.5, "unit": "%"}],
        checkable=True
    )
    confirmed_evidence = [
        Evidence(
            id="e1",
            engine="google",
            title="Monetary Policy Statement, 2024-25: Resolution of the Monetary Policy Committee",
            source="Reserve Bank of India",
            tier=1,
            date="Dec 6, 2024",
            snippet="The Monetary Policy Committee (MPC) at its meeting today decided to keep the policy repo rate under the liquidity adjustment facility (LAF) unchanged at 6.50 per cent.",
            url="https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=116028"
        )
    ]

    numeric_check, status = check_numeric_claim(claim, confirmed_evidence)
    assert numeric_check is not None
    assert numeric_check["within_tolerance"] is True
    assert numeric_check["claimed"] == 6.5
    assert numeric_check["actual"] == 6.50

    judgment = judge_claim(claim, confirmed_evidence)
    assert judgment.label == VerdictLabel.SUPPORTED
    assert judgment.confidence == "High"
    assert "e1" in judgment.evidence_ids
    assert "6.5%" in judgment.rationale
    assert "Reserve Bank of India" in judgment.rationale
