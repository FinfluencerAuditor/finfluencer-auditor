"""Offline end-to-end evidence preservation checks across unrelated claims."""

import asyncio
from unittest.mock import Mock

import httpx
import pytest

from app import pipeline
from app import main
from app.retrieve import parse_engine_response, retrieve_claim
from app.schemas import Claim, Judgment, TranscriptSegment, VerdictLabel, VideoMetadata


def _claim(claim_id, text, domain):
    return Claim(
        id=claim_id, original_text=text, normalized_text=text, start_seconds=0,
        domain=domain, claim_type="statistic", checkable=True,
    )


def test_all_relevant_distinct_sources_survive_filtering_and_normalization():
    claim = _claim("finance-1", "Acme shares returned 12% during 2024.", "finance")
    results = [
        {
            "title": f"Acme shares returned 12% in report {index}",
            "link": f"https://sources.example/report-{index}",
            "snippet": f"Acme shares returned 12% during 2024, according to report {index}.",
            "source": f"Source {index}",
            "date": "2024-12-31",
        }
        for index in range(6)
    ]
    # The repeated URL is a duplicate; the six distinct URLs must remain.
    results.append({**results[0], "title": "Duplicate copy"})
    serp = Mock()
    serp.search.return_value = {"organic_results": results}

    evidence, status = retrieve_claim(claim, serp)

    assert status == "complete"
    assert len(evidence) == 6
    assert {item.url for item in evidence} == {f"https://sources.example/report-{i}" for i in range(6)}
    assert all(item.date == "2024-12-31" and item.snippet and item.source for item in evidence)


def test_irrelevant_health_result_is_rejected_and_missing_evidence_is_explicit():
    claim = _claim("health-1", "Vitamin D reduces fracture risk by 20% in adults.", "health")
    serp = Mock()
    serp.search.return_value = {"organic_results": [
        {
            "title": "Vitamin D supplements and fracture risk",
            "link": "https://medical.example/vitamin-d",
            "snippet": "A study found Vitamin D reduced fracture risk by 20% in adults.",
        },
        {
            "title": "Vitamin D recipes and sunlight facts",
            "link": "https://unrelated.example/recipes",
            "snippet": "Vitamin D is discussed in recipes and sunlight advice.",
        },
    ]}

    evidence, status = retrieve_claim(claim, serp)

    assert status == "complete"
    assert [item.url for item in evidence] == ["https://medical.example/vitamin-d"]

    empty_serp = Mock()
    empty_serp.search.return_value = {"organic_results": []}
    no_evidence, _ = retrieve_claim(_claim("general-1", "An unknown event happened in 1891.", "other"), empty_serp)
    assert no_evidence == []


def test_parse_normalize_pipeline_serialization_and_claim_isolation(monkeypatch):
    parsed = parse_engine_response("google_news", {"news_results": [
        {"title": "Company A result", "link": "https://news.example/a", "snippet": "Company A rose 8%.", "date": "2025-01-02", "source": {"name": "News A"}},
        {"title": 17.5, "link": "https://news.example/b", "snippet": 22.0, "source": {"name": 4.0}},
    ]})
    assert parsed[0]["title"] == "Company A result"
    assert parsed[0]["date"] == "2025-01-02"
    assert parsed[1]["title"] == "17.5" and parsed[1]["snippet"] == "22.0"

    claims = [
        _claim("finance-claim", "Company A rose 8%.", "finance"),
        _claim("health-claim", "Vitamin D reduces fracture risk by 20%.", "health"),
    ]
    monkeypatch.setattr(pipeline.db, "save_claim", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.db, "save_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "ingest", lambda url, serp: (VideoMetadata(video_id="offline", title="Offline", url=url), []))
    monkeypatch.setattr(pipeline, "extract_claims", lambda segments, provider: claims)

    evidence_by_claim = {
        "finance-claim": [{"id": "f1", "engine": "google_news", "url": "https://news.example/a", "title": "Company A", "snippet": "Company A rose 8%.", "source": "News A", "tier": 2, "date": "2025-01-02"}],
        "health-claim": [{"id": "h1", "engine": "google_scholar", "url": "https://medical.example/d", "title": "Vitamin D study", "snippet": "Vitamin D reduced fracture risk by 20%.", "source": "Medical A", "tier": 1, "date": None}],
    }

    def retrieve(claim, serp, *_diagnostics):
        from app.schemas import Evidence
        return [Evidence(**item) for item in evidence_by_claim[claim.id]], "complete"

    monkeypatch.setattr(pipeline, "retrieve_claim", retrieve)
    monkeypatch.setattr(pipeline, "judge_claim", lambda claim, evidence, provider, metadata: Judgment(
        claim_id=claim.id, label=VerdictLabel.SUPPORTED, rationale="Evidence matched.", evidence_ids=[evidence[0].id],
    ))

    score = asyncio.run(pipeline.AuditPipeline(serp=object(), provider=None).run("offline", "https://youtu.be/offline"))
    payload = score.model_dump(mode="json")
    assert [item["claim"]["id"] for item in payload["claims"]] == ["finance-claim", "health-claim"]
    assert payload["claims"][0]["evidence"][0]["url"] == "https://news.example/a"
    assert payload["claims"][1]["evidence"][0]["url"] == "https://medical.example/d"
    assert payload["claims"][0]["evidence"][0]["id"] != payload["claims"][1]["evidence"][0]["id"]


@pytest.mark.anyio
async def test_real_pipeline_api_path_preserves_verdicts_and_evidence(monkeypatch):
    claims = [
        Claim(id="supported", original_text="Acme revenue increased 12% in 2024.", normalized_text="Acme revenue increased 12% in 2024.", start_seconds=0, domain="finance", claim_type="statistic", numeric_info=[{"original": "12%"}], entities={"named_entities": ["Acme"]}),
        Claim(id="contradicted", original_text="Beta revenue increased 20% in 2024.", normalized_text="Beta revenue increased 20% in 2024.", start_seconds=1, domain="finance", claim_type="statistic", numeric_info=[{"original": "20%"}], entities={"named_entities": ["Beta"]}),
        Claim(id="mixed", original_text="Gamma revenue increased 10% in 2024.", normalized_text="Gamma revenue increased 10% in 2024.", start_seconds=2, domain="finance", claim_type="statistic", numeric_info=[{"original": "10%"}], entities={"named_entities": ["Gamma"]}),
        Claim(id="irrelevant", original_text="Delta revenue increased 15% in 2024.", normalized_text="Delta revenue increased 15% in 2024.", start_seconds=3, domain="finance", claim_type="statistic", numeric_info=[{"original": "15%"}], entities={"named_entities": ["Delta"]}),
        Claim(id="missing", original_text="Epsilon revenue increased 30% in 2024.", normalized_text="Epsilon revenue increased 30% in 2024.", start_seconds=4, domain="finance", claim_type="statistic", numeric_info=[{"original": "30%"}], entities={"named_entities": ["Epsilon"]}),
    ]

    responses = {
        "Acme": [{"title": "Acme revenue increased 12%", "link": "https://reuters.com/acme", "snippet": "Acme revenue increased 12% in 2024.", "source": "Reuters", "date": "2024-12-31"}],
        "Beta": [{"title": "Beta revenue did not increase 20%", "link": "https://sec.gov/beta", "snippet": "Beta revenue did not increase 20% in 2024; it fell instead.", "source": "SEC", "date": "2024-12-31"}],
        "Gamma": [
            {"title": "Gamma revenue increased 10%", "link": "https://reuters.com/gamma", "snippet": "Gamma revenue increased 10% in 2024.", "source": "Reuters", "date": "2024-12-31"},
            {"title": "Gamma revenue did not increase 10%", "link": "https://sec.gov/gamma", "snippet": "Gamma revenue did not increase 10% in 2024; it declined.", "source": "SEC", "date": "2024-12-31"},
        ],
        "Delta": [{"title": "Delta mentioned in a general market overview", "link": "https://example.org/market", "snippet": "The market overview lists Delta among companies discussed by investors.", "source": "Example", "date": "2024-12-31"}],
        "Epsilon": [],
    }

    class FakeSerp:
        def search(self, _engine, **params):
            query = params.get("q", "")
            for name, items in responses.items():
                if name.lower() in query.lower():
                    return {"organic_results": items}
            return {"organic_results": []}

    saved = {}
    monkeypatch.setattr(pipeline.db, "save_claim", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.db, "save_audit", lambda aid, vid, status, payload: saved.update({"id": aid, "status": status, "payload": payload}))
    monkeypatch.setattr(pipeline, "ingest", lambda url, serp: (VideoMetadata(video_id="offline", title="Offline fixture", url=url), [TranscriptSegment(index=0, start_seconds=0, end_seconds=5, text_original="fixture")]))
    monkeypatch.setattr(pipeline, "extract_claims", lambda segments, provider: claims)

    score = await pipeline.AuditPipeline(serp=FakeSerp(), provider=None).run("offline-e2e", "https://youtu.be/offline")
    assert saved["id"] == "offline-e2e"
    payload = saved["payload"]
    labels = {row["claim"]["id"]: row["judgment"]["label"] for row in payload["claims"]}
    assert labels == {"supported": "Supported", "contradicted": "Contradicted", "mixed": "Mixed", "irrelevant": "No evidence found", "missing": "No evidence found"}
    assert sum(payload["summary"]["verdict_counts"].values()) == len(payload["claims"]) == 5
    assert payload["claims"][0]["judgment"]["analysis_mode"] == "deterministic_fallback"
    assert payload["claims"][0]["evidence"][0]["url"] == "https://reuters.com/acme"
    assert set(payload["claims"][2]["judgment"]["evidence_ids"]) == {"e1", "e2"}
    assert payload["claims"][3]["evidence"] == []
    assert payload["claims"][4]["evidence"] == []

    main.tasks["offline-e2e"] = score
    try:
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/audits/offline-e2e")
        api_payload = response.json()
        assert response.status_code == 200
        assert api_payload["claims"][0]["evidence"][0]["title"] == "Acme revenue increased 12%"
        assert api_payload["claims"][1]["judgment"]["label"] == "Contradicted"
        assert api_payload["claims"][2]["judgment"]["label"] == "Mixed"
    finally:
        main.tasks.pop("offline-e2e", None)
