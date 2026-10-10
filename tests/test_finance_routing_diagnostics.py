"""Offline coverage for finance provider selection and retrieval diagnostics."""

from unittest.mock import Mock

import pytest

from app.retrieve import draft_queries, retrieve_claim, route_claim
from app.schemas import Claim
from app.serp import SerpApiClient, SerpApiError


def _claim(text, *, entity=None):
    return Claim(
        id="routing-fixture",
        original_text=text,
        normalized_text=text,
        start_seconds=0,
        domain="finance",
        claim_type="statistic",
        checkable=True,
        entities={"named_entities": [entity]} if entity else {},
    )


@pytest.mark.parametrize(
    "text,entity,finance_expected",
    [
        ("ACME's current share price is 125.", "ACME", True),
        ("Acme shares returned 12% during 2024.", "Acme", False),
        ("Active funds underperform index funds after fees.", "active funds", False),
        ("Index funds charge 0.19% while active funds charge 0.85%.", "index funds", False),
        ("Diversification can reduce portfolio risk.", "portfolio", False),
    ],
)
def test_finance_routing_matches_claim_scope(text, entity, finance_expected):
    engines = route_claim(_claim(text, entity=entity))
    assert ("google_finance" in engines) is finance_expected
    assert "google_news" in engines and "google" in engines


def test_historical_and_fee_queries_keep_assertion_context():
    claims = [
        (_claim("Acme shares returned 12% during 2024.", entity="Acme"), ["acme", "returned", "12", "2024"]),
        (_claim("Index funds charge 0.19% while active funds charge 0.85%.", entity="index funds"), ["index", "funds", "charge", "0.19", "active", "0.85"]),
    ]
    for claim, required_terms in claims:
        query_text = " ".join(spec["q"].lower() for spec in draft_queries(claim))
        for term in required_terms:
            assert term in query_text
        assert all(spec["engine"] != "google_finance" for spec in draft_queries(claim))


def test_title_case_company_name_is_not_invented_as_a_ticker():
    claim = _claim("Acme's current share price is 125.", entity="Acme")
    queries = draft_queries(claim)
    assert all(spec["engine"] != "google_finance" for spec in queries)


def test_cache_key_separates_engine_query_and_context():
    key = SerpApiClient.cache_key
    assert key("google", {"q": "Acme price", "gl": "us"}) != key("google_news", {"q": "Acme price", "gl": "us"})
    assert key("google", {"q": "Acme price", "gl": "us"}) != key("google", {"q": "Acme price", "gl": "in"})
    assert key("google", {"q": "Acme price"}) != key("google", {"q": "Acme returns"})


def test_diagnostics_distinguish_cache_hit_empty_and_normalized_results():
    class CachedProvider:
        last_search = {"status": "cache_hit", "cache_hit": True}

        def search(self, engine, **_params):
            if engine == "google_news":
                return {"news_results": [{
                    "title": "Acme share price is 125",
                    "link": "https://example.test/acme-price",
                    "snippet": "Acme's share price is 125.",
                }]}
            return {"organic_results": []}

    diagnostics = {}
    evidence, status = retrieve_claim(_claim("Acme's current share price is 125.", entity="Acme"), CachedProvider(), diagnostics)
    assert status == "complete"
    assert len(evidence) == 1
    events = diagnostics["events"]
    assert any(event["event"] == "search_result" and event["cache_hit"] for event in events)
    assert any(event["event"] == "parsed_results" and event["parsed_count"] == 1 for event in events)
    complete = events[-1]
    assert complete["raw_result_count"] >= 1
    assert complete["evidence_count"] == 1
    assert complete["status"] == "complete"


def test_empty_success_is_not_provider_failure():
    class EmptyProvider:
        last_search = {"status": "live_success", "cache_hit": False}

        def search(self, *_args, **_kwargs):
            return {"organic_results": []}

    diagnostics = {}
    evidence, status = retrieve_claim(_claim("Acme shares returned 12%.", entity="Acme"), EmptyProvider(), diagnostics)
    assert evidence == [] and status == "complete"
    assert any(event["event"] == "empty_response" for event in diagnostics["events"])
    assert diagnostics["events"][-1]["status"] == "complete"


def test_provider_error_is_failed_and_not_misreported_as_empty_or_quota():
    class FailedProvider:
        last_search = {"status": "error", "cache_hit": False, "error_type": "SerpApiError"}

        def search(self, *_args, **_kwargs):
            raise SerpApiError("offline provider fixture failure")

    diagnostics = {}
    evidence, status = retrieve_claim(_claim("Acme shares returned 12%.", entity="Acme"), FailedProvider(), diagnostics)
    assert evidence == [] and status == "failed"
    assert any(event["event"] == "search_error" for event in diagnostics["events"])
    assert all("quota" not in str(event).lower() for event in diagnostics["events"])
    assert diagnostics["events"][-1]["status"] == "failed"

