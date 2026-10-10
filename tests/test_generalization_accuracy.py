"""Offline regression tests for claim-specific evidence integrity."""

from unittest.mock import Mock

import pytest

from app.extract import ExtractedClaims, extract_claims
from app.retrieve import compute_claim_relevance, retrieve_claim, draft_queries, parse_engine_response
from app.schemas import Claim, Evidence, TranscriptSegment, VerdictLabel
from app.judge import judge_claim


def _claim(text, **kwargs):
    return Claim(
        id="regression",
        original_text=text,
        normalized_text=text,
        start_seconds=0,
        domain=kwargs.pop("domain", "finance"),
        claim_type=kwargs.pop("claim_type", "statistic"),
        checkable=True,
        **kwargs,
    )


def test_same_entity_wrong_number_and_period_is_not_relevant():
    claim = _claim("The Nifty 50 fell 10% in 2020.", entities={"named_entities": ["Nifty 50"]})
    wrong = {
        "title": "Nifty 50 fell 4% in 2021",
        "snippet": "The Nifty 50 fell 4% during 2021.",
        "url": "https://example.test/nifty",
    }
    assert compute_claim_relevance(wrong, claim, ["nifty", "fell", "10", "2020"]) == 0


def test_causal_claim_requires_causal_language():
    claim = _claim(
        "Vitamin D prevents diabetes.",
        domain="health",
        entities={"health_terms": ["Vitamin D", "diabetes"]},
    )
    item = {"title": "Vitamin D and diabetes", "snippet": "Vitamin D levels and diabetes were studied."}
    assert compute_claim_relevance(item, claim, ["vitamin", "prevents", "diabetes"]) == 0


def test_retrieval_discards_missing_urls_and_empty_snippets():
    claim = _claim("The Nifty 50 fell 10%.", entities={"named_entities": ["Nifty 50"]})
    serp = Mock()
    serp.search.return_value = {"organic_results": [
        {"title": "Nifty 50 fell 10%", "snippet": "Nifty 50 fell 10%.", "link": ""},
        {"title": "Nifty 50 fell 10%", "snippet": "", "link": "https://example.test/empty"},
        {"title": "Nifty 50 fell 10%", "snippet": "The Nifty 50 fell 10%.", "link": "https://example.test/valid"},
    ]}
    evidence, status = retrieve_claim(claim, serp)
    assert status in {"complete", "failed"}
    assert [item.url for item in evidence] == ["https://example.test/valid"]


def test_model_timestamp_is_preserved_when_supplied():
    segments = [TranscriptSegment(index=0, start_seconds=0, end_seconds=2, text_original="The market fell 10%.")]

    class Provider:
        def structured(self, *_args):
            return ExtractedClaims(claims=[Claim(
                original_text="The market fell 10%.", normalized_text="The market fell 10%.",
                start_seconds=0, end_seconds=2, domain="finance", claim_type="statistic",
                checkable=True,
            )])

    claims = extract_claims(segments, Provider())
    assert claims[0].start_seconds == 0 and claims[0].end_seconds == 2


def test_deterministic_fallback_splits_independent_percentage_assertions():
    segments = [TranscriptSegment(index=0, start_seconds=0, end_seconds=3, text_original="The Nifty fell 10% and the Sensex fell 5%.")]
    claims = extract_claims(segments)
    assert len(claims) == 2
    assert {c.numeric_info[0]["value"] for c in claims} == {10.0, 5.0}


def test_wrong_period_evidence_cannot_support_claim():
    claim = _claim("The Nifty 50 fell 10% in 2020.", entities={"named_entities": ["Nifty 50"]})
    evidence = [Evidence(
        id="e1", engine="google", title="Nifty 50 fell 10% in 2021",
        source="Example", tier=1, snippet="The Nifty 50 fell 10% in 2021.",
        url="https://example.test/nifty",
    )]
    assert judge_claim(claim, evidence).label == VerdictLabel.NO_EVIDENCE


def test_historical_finance_claim_uses_assertion_search_not_ticker_lookup():
    claim = _claim(
        "The Nifty 50 fell 10% during October 2024.",
        entities={"named_entities": ["Nifty 50"]},
    )
    queries = draft_queries(claim)
    assert not any(item["engine"] == "google_finance" for item in queries)
    assert any("10" in item["q"] and "2024" in item["q"] for item in queries)


def test_entity_only_social_result_is_rejected_for_metric_claim():
    claim = _claim(
        "Palantir beta is 1.5.",
        entities={"named_entities": ["Palantir"]},
    )
    item = {
        "title": "Palantir discussed by investors",
        "snippet": "Palantir is a popular software company with a growing community.",
        "url": "https://example.test/palantir",
    }
    assert compute_claim_relevance(item, claim, ["palantir", "beta", "1.5"]) == 0


def test_relevant_incomplete_snippet_survives_when_assertion_is_addressed():
    claim = _claim(
        "The Nifty 50 fell 10% during October 2024.",
        entities={"named_entities": ["Nifty 50"]},
    )
    item = {
        "title": "Nifty 50 fell sharply in October",
        "snippet": "The index fell sharply during the October sell-off.",
        "date": None,
        "url": "https://example.test/nifty-october",
    }
    assert compute_claim_relevance(item, claim, ["nifty", "fell", "10", "2024"]) > 0


def test_alternate_finance_response_shape_is_parsed():
    items = parse_engine_response("google_finance", {"finance_results": [{
        "name": "Example Ltd", "price": "100", "beta": "1.2", "date": "2024-10-01"
    }]})
    assert len(items) == 1
    assert items[0]["title"] == "Example Ltd"
    assert "Beta: 1.2" in items[0]["snippet"]


def test_opt_in_diagnostics_record_search_and_rejection_stages():
    class FakeSerp:
        last_search = {"status": "cache_hit", "cache_hit": True}

        def search(self, _engine, **_params):
            return {"organic_results": [
                {"title": "Nifty 50 fell 10%", "link": "", "snippet": "Nifty 50 fell 10%."},
            ]}

    diagnostics = {}
    evidence, status = retrieve_claim(
        _claim("The Nifty 50 fell 10%.", entities={"named_entities": ["Nifty 50"]}),
        FakeSerp(), diagnostics,
    )
    assert status == "complete" and evidence == []
    events = {event["event"] for event in diagnostics["events"]}
    assert {"claim_start", "search_result", "parsed_results", "claim_complete"} <= events
    assert diagnostics["events"][-1]["rejection_counts"]["invalid_url"] == 1


@pytest.mark.parametrize(
    "domain,text,entity,terms",
    [
        ("finance", "Acme shares returned 12% during 2024.", "Acme", ["acme", "returned", "12%", "2024"]),
        ("finance", "The portfolio has 40% concentration in one sector.", "portfolio", ["portfolio", "40%", "concentration"]),
        ("health", "Vitamin D reduces fracture risk by 20% in adults over 65.", "Vitamin D", ["vitamin", "d", "reduces", "20%", "fracture"]),
        ("health", "The treatment does not reduce mortality in severe disease.", "treatment", ["treatment", "does", "not", "reduce", "mortality"]),
    ],
)
def test_queries_preserve_subject_assertion_qualifiers_and_quantities(domain, text, entity, terms):
    claim = _claim(text, domain=domain, entities={"named_entities": [entity]})
    query_text = " ".join(item["q"].lower() for item in draft_queries(claim))
    for term in terms:
        assert term in query_text


def test_malformed_engine_fields_are_normalized_without_losing_valid_results():
    items = parse_engine_response("google_news", {"news_results": [
        {"title": 42.0, "snippet": 17.5, "link": 99, "source": {"name": 4.0}},
        {"title": "Valid result", "snippet": "The treatment reduced symptoms.", "url": "https://example.org/valid"},
    ]})
    assert len(items) == 2
    assert items[0]["title"] == "42.0"
    assert items[0]["snippet"] == "17.5"
    assert items[1]["url"] == "https://example.org/valid"


def test_empty_and_malformed_responses_are_distinguishable_in_diagnostics():
    class Responses:
        last_search = {"status": "cache_hit", "cache_hit": True}
        values = [None, ["not an object"], {"news_results": []}]

        def search(self, *_args, **_kwargs):
            return self.values.pop(0)

    diagnostics = {}
    evidence, status = retrieve_claim(
        _claim("Acme shares returned 12%.", entities={"named_entities": ["Acme"]}),
        Responses(), diagnostics,
    )
    events = {event["event"] for event in diagnostics["events"]}
    assert evidence == []
    assert status in {"complete", "failed"}
    assert "empty_response" in events
    assert "parse_failure" in events
