from unittest.mock import Mock
import pytest
from app.retrieve import (
    route_claim,
    draft_queries,
    parse_engine_response,
    retrieve_claim,
)
from app.schemas import Claim, Evidence
from app.serp import SerpApiClient, SerpApiError


def test_routing_by_domain():
    fin_claim = Claim(id="c1", original_text="Reliance PE is 25", start_seconds=0, domain="finance")
    health_claim = Claim(id="c2", original_text="Turmeric cures cancer", start_seconds=0, domain="health")
    other_claim = Claim(id="c3", original_text="General news statement", start_seconds=0, domain="other")

    assert "google_finance" in route_claim(fin_claim)
    assert "google_scholar" in route_claim(health_claim)
    assert route_claim(other_claim) == ["google_news", "google"]


def test_draft_queries_budget_cap():
    claim = Claim(
        id="c1",
        original_text="Dosto aaj video mein Reliance Industries Q2 profit rose 10 percent dekhiye subscribe kijiye",
        normalized_text="Reliance Industries Q2 net profit increased by 10 percent",
        start_seconds=10,
        domain="finance",
        entities={"mentions": ["Reliance Industries", "RELIANCE"]}
    )
    queries = draft_queries(claim)
    assert len(queries) <= 3
    assert all("engine" in q for q in queries)
    assert any("reliance" in str(q.get("q", "")).lower() for q in queries)


def test_parse_google_news_response():
    sample_news = {
        "news_results": [
            {
                "title": "SEBI tightens F&O rules to curb retail frenzy",
                "link": "https://www.moneycontrol.com/news/business/markets/sebi-fo-rules.html",
                "source": {"name": "Moneycontrol"},
                "date": "2 hours ago",
                "snippet": "SEBI on Tuesday announced new index derivatives framework."
            }
        ]
    }
    items = parse_engine_response("google_news", sample_news)
    assert len(items) == 1
    assert items[0]["title"] == "SEBI tightens F&O rules to curb retail frenzy"
    assert items[0]["source"] == "Moneycontrol"
    assert items[0]["url"] == "https://www.moneycontrol.com/news/business/markets/sebi-fo-rules.html"


def test_parse_google_scholar_response():
    sample_scholar = {
        "organic_results": [
            {
                "title": "Curcumin in inflammation and clinical outcomes",
                "link": "https://www.sciencedirect.com/science/article/pii/S001",
                "publication_info": {"summary": "BB Aggarwal - The Lancet, 2023 - Elsevier"},
                "snippet": "A systematic review demonstrating clinical modulation of inflammatory pathways.",
                "inline_links": {"cited_by": {"total": 450}}
            }
        ]
    }
    items = parse_engine_response("google_scholar", sample_scholar)
    assert len(items) == 1
    assert "Curcumin" in items[0]["title"]
    assert items[0]["metadata"]["cited_by"] == 450
    assert "sciencedirect.com" in items[0]["url"]


def test_parse_google_finance_response():
    sample_finance = {
        "summary": {
            "title": "Reliance Industries Ltd",
            "stock": "RELIANCE:NSE",
            "price": "2,745.50",
            "pe_ratio": "26.4",
            "market_cap": "18.5T"
        }
    }
    items = parse_engine_response("google_finance", sample_finance)
    assert len(items) == 1
    assert "Reliance Industries" in items[0]["title"]
    assert "Price: 2,745.50" in items[0]["snippet"]


def test_parse_google_finance_numeric_values_and_malformed_fields_are_safe():
    """SerpApi may return JSON numbers, and one malformed field must not abort parsing."""
    sample_finance = {
        "summary": {
            "title": "Example Index",
            "price": 2745.5,
            "pe_ratio": 26.4,
            "market_cap": None,
            6.4: "malformed numeric key",
        },
        "finance_results": [{"name": "Example Index", "price": 2745.5, "beta": 1.2}],
    }
    items = parse_engine_response("google_finance", sample_finance)
    assert len(items) == 2
    assert "Price: 2745.5" in items[0]["snippet"]
    assert "Beta: 1.2" in items[1]["snippet"]


def test_numeric_claim_malformed_values_fail_gracefully():
    claim = Claim(
        id="numeric-malformed",
        original_text="The index grew by 10%.",
        normalized_text="The index grew by 10%.",
        start_seconds=0,
        domain="finance",
        claim_type="statistic",
        numeric_info=[{"original": "10%", "value": 10.0, "unit": "%"}, {"value": None}],
    )
    evidence, state = retrieve_claim(claim, Mock())
    assert state in {"complete", "failed"}
    assert isinstance(evidence, list)


def test_retrieve_claim_uncheckable_skips_search():
    claim = Claim(
        id="c1",
        original_text="This stock will double in 10 days.",
        start_seconds=0,
        claim_type="prediction",
        checkable=False
    )
    mock_serp = Mock()
    evidence, state = retrieve_claim(claim, mock_serp)
    assert evidence == []
    assert state == "complete"
    assert mock_serp.search.call_count == 0


def test_retrieve_claim_with_mock_serp():
    claim = Claim(
        id="c1",
        original_text="SEBI issues notice to unregistered advisors.",
        normalized_text="SEBI issues notice to unregistered advisors.",
        start_seconds=15,
        domain="finance",
        checkable=True
    )
    mock_serp = Mock()
    mock_serp.search.return_value = {
        "organic_results": [
            {
                "title": "SEBI Order on Finfluencers",
                "link": "https://www.sebi.gov.in/enforcement/orders/2024/order.html",
                "snippet": "SEBI takes action against unregistered entities.",
                "source": "SEBI"
            }
        ]
    }
    evidence, state = retrieve_claim(claim, mock_serp)
    assert state == "complete"
    assert len(evidence) == 1
    assert evidence[0].tier == 1
    assert evidence[0].id == "e1"
    assert evidence[0].url == "https://www.sebi.gov.in/enforcement/orders/2024/order.html"


def test_retrieve_claim_failure_state():
    claim = Claim(
        id="c1",
        original_text="Check this claim.",
        normalized_text="Check this claim.",
        start_seconds=0,
        domain="finance",
        checkable=True
    )
    mock_serp = Mock()
    mock_serp.search.side_effect = SerpApiError("Network timeout connecting to SerpApi")
    evidence, state = retrieve_claim(claim, mock_serp)
    assert evidence == []
    assert state == "failed"
