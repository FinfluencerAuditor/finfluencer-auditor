import asyncio
from unittest.mock import Mock
from app import pipeline
from app.schemas import VideoMetadata, TranscriptSegment, VerdictLabel
from app.extract import ExtractedClaims
from app.schemas import Claim


def test_explicit_none_provider_disables_auto_provider(monkeypatch):
    """An explicit None must select deterministic fallback, not live Gemini."""
    def unexpected_auto_provider():
        raise AssertionError("auto provider should not be loaded")

    monkeypatch.setattr(pipeline, "get_provider", unexpected_auto_provider)
    audit_pipeline = pipeline.AuditPipeline(serp=Mock(), provider=None)

    assert audit_pipeline.provider is None


class Provider:
    def structured(self, operation, prompt, schema):
        return ExtractedClaims(claims=[
            Claim(
                original_text="The Nifty 50 fell 10 percent.",
                normalized_text="The Nifty 50 fell 10 percent.",
                start_seconds=0,
                end_seconds=2,
                domain="finance",
                claim_type="statistic",
                checkable=True
            ),
            Claim(
                original_text="This stock will 100x next year guaranteed.",
                normalized_text="This stock will 100x next year guaranteed.",
                start_seconds=5,
                end_seconds=8,
                domain="finance",
                claim_type="prediction",
                checkable=False
            )
        ])


def test_pipeline_progress_and_claim_failure_isolation(monkeypatch):
    monkeypatch.setattr(pipeline.db, "save_claim", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.db, "save_audit", lambda *args, **kwargs: None)
    async def direct_to_thread(function, *args):
        return function(*args)
    monkeypatch.setattr(pipeline.asyncio, "to_thread", direct_to_thread)
    monkeypatch.setattr(pipeline, "ingest", lambda url, serp: (VideoMetadata(video_id="x", title="t", url=url), [TranscriptSegment(index=0, start_seconds=0, end_seconds=2, text_original="Nifty 50 fell 10 percent.")]))
    monkeypatch.setattr(pipeline, "retrieve_claim", lambda claim, serp: ([], "not_implemented"))
    events = []
    score = asyncio.run(pipeline.AuditPipeline(serp=object(), provider=Provider()).run("audit-test", "https://youtu.be/abcdefghijk", events.append))
    assert score.status.value == "complete" and len(score.claims) == 2
    assert [event.stage for event in events] == ["ingest", "extract", "claims", "claims", "complete"]
    assert events[-1].progress == 1


def test_pipeline_end_to_end_with_person_b(monkeypatch):
    monkeypatch.setattr(pipeline.db, "save_claim", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.db, "save_audit", lambda *args, **kwargs: None)
    async def direct_to_thread(function, *args):
        return function(*args)
    monkeypatch.setattr(pipeline.asyncio, "to_thread", direct_to_thread)

    mock_serp = Mock()
    mock_serp.search.return_value = {
        "organic_results": [
            {
                "title": "Nifty drops 10% in October",
                "link": "https://www.reuters.com/markets/nifty10",
                "snippet": "Nifty fell 10% amid heavy global equity selling.",
                "source": "reuters.com"
            }
        ]
    }

    pipe = pipeline.AuditPipeline(serp=mock_serp, provider=Provider())
    events = []
    monkeypatch.setattr(pipeline, "ingest", lambda url, serp: (
        VideoMetadata(video_id="test1234", title="Market Analysis", url=url),
        [TranscriptSegment(index=0, start_seconds=0, end_seconds=2, text_original="Nifty 50 fell 10 percent.")]
    ))

    score = asyncio.run(pipe.run("audit-e2e", "https://youtu.be/test1234", events.append))
    assert score.status.value == "complete"
    assert len(score.claims) == 2

    # Claim 1: Checkable statistic with matching evidence -> Supported
    claim1_res = score.claims[0]
    assert claim1_res.state == "complete"
    assert claim1_res.judgment is not None
    assert claim1_res.judgment.label == VerdictLabel.SUPPORTED
    assert len(claim1_res.evidence) >= 1

    # Claim 2: Uncheckable prediction -> Unverifiable
    claim2_res = score.claims[1]
    assert claim2_res.state == "complete"
    assert claim2_res.judgment is not None
    assert claim2_res.judgment.label == VerdictLabel.UNVERIFIABLE
    assert sum(claim1_res.judgment.label == label for label in VerdictLabel) == 1
    assert sum(score.summary.verdict_counts.values()) == len(score.claims)


def test_pipeline_unexpected_exception_marks_failed(monkeypatch):
    """An unexpected exception during extraction or judging must mark the audit as FAILED, never leaving it pending."""
    saved_audits = []
    monkeypatch.setattr(pipeline.db, "save_claim", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.db, "save_audit", lambda aid, vid, status, payload: saved_audits.append((aid, status, payload)))
    async def direct_to_thread(function, *args):
        return function(*args)
    monkeypatch.setattr(pipeline.asyncio, "to_thread", direct_to_thread)

    def crashing_extract(*args, **kwargs):
        raise RuntimeError("Unexpected extraction crash")

    monkeypatch.setattr(pipeline, "ingest", lambda url, serp: (
        VideoMetadata(video_id="crash_test", title="Crash Test", url=url),
        [TranscriptSegment(index=0, start_seconds=0, end_seconds=2, text_original="Some text")]
    ))
    monkeypatch.setattr(pipeline, "extract_claims", crashing_extract)

    pipe = pipeline.AuditPipeline(serp=Mock(), provider=None)
    events = []
    score = asyncio.run(pipe.run("audit-crash-123", "https://youtu.be/crash_test", events.append))

    assert score.status.value == "failed"
    assert "Unexpected extraction crash" in (score.error or "")
    assert any(status == "failed" for _, status, _ in saved_audits)
    assert events[-1].stage == "failed"
