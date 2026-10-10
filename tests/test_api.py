import asyncio
import time
import httpx
import pytest
from app.main import app, health
from app.schemas import AuditRequest


def test_health():
    assert health()["status"] == "ok"


def test_submission_request_schema():
    request = AuditRequest(url="https://youtu.be/dQw4w9WgXcQ")
    assert request.url.endswith("dQw4w9WgXcQ")


@pytest.mark.anyio
async def test_submit_returns_202_immediately(monkeypatch):
    class MockAuditPipeline:
        async def run(self, audit_id, url, progress):
            pass
    monkeypatch.setattr("app.main.AuditPipeline", MockAuditPipeline)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        start = time.time()
        resp = await client.post("/api/audits", json={"url": "https://www.youtube.com/watch?v=whEq6V6thrg"})
        duration = time.time() - start
        assert resp.status_code == 202
        data = resp.json()
        assert "audit_id" in data
        assert data["status"] == "pending"
        # Must return promptly without waiting for the full audit pipeline
        assert duration < 1.0


@pytest.mark.anyio
async def test_get_audit_retrieves_persisted(monkeypatch):
    class MockAuditPipeline:
        async def run(self, audit_id, url, progress):
            from app.schemas import AuditScorecard, AuditStatus
            return AuditScorecard(audit_id=audit_id, status=AuditStatus.PENDING)
    monkeypatch.setattr("app.main.AuditPipeline", MockAuditPipeline)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/audits", json={"url": "https://www.youtube.com/watch?v=LO-gNRiK0Aw"})
        aid = resp.json()["audit_id"]
        get_resp = await client.get(f"/api/audits/{aid}")
        assert get_resp.status_code == 200
        audit_data = get_resp.json()
        assert audit_data["audit_id"] == aid
        assert audit_data["status"] in {"pending", "complete", "running"}


@pytest.mark.anyio
async def test_api_full_audit_lifecycle(monkeypatch):
    """Test full API lifecycle where POST /api/audits schedules task and GET returns completed scorecard with claims & evidence."""
    from app.schemas import AuditScorecard, AuditStatus, AuditSummary, ClaimResult, Claim, Evidence, Judgment, VerdictLabel, VideoMetadata

    mock_claim = Claim(
        id="c1",
        original_text="The Nifty 50 fell 10 percent in October.",
        normalized_text="The Nifty 50 fell 10 percent in October.",
        start_seconds=0,
        domain="finance",
        claim_type="statistic",
        checkable=True
    )
    mock_ev = Evidence(
        id="e1",
        engine="google_news",
        title="Nifty drops 10% in October",
        source="reuters.com",
        tier=2,
        snippet="Nifty fell 10% amid broad market correction.",
        url="https://reuters.com/nifty"
    )
    mock_judgment = Judgment(
        claim_id="c1",
        label=VerdictLabel.SUPPORTED,
        confidence="High",
        rationale="Verified against Reuters reporting.",
        evidence_ids=["e1"]
    )
    mock_score = AuditScorecard(
        audit_id="aid-lifecycle-test",
        status=AuditStatus.COMPLETE,
        metadata=VideoMetadata(video_id="life123", title="Lifecycle Video", url="https://youtu.be/life123"),
        claims=[
            ClaimResult(claim=mock_claim, evidence=[mock_ev], judgment=mock_judgment, state="complete")
        ],
        summary=AuditSummary(
            total_claims=1,
            checkable_claims=1,
            risk_flags=0,
            verdict_counts={"Supported": 1, "Contradicted": 0, "Mixed": 0, "No evidence found": 0, "Unverifiable": 0}
        )
    )

    class MockPipeline:
        async def run(self, audit_id, url, progress):
            mock_score.audit_id = audit_id
            return mock_score

    monkeypatch.setattr("app.main.AuditPipeline", MockPipeline)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        post_resp = await client.post("/api/audits", json={"url": "https://youtu.be/life123"})
        assert post_resp.status_code == 202
        aid = post_resp.json()["audit_id"]

        # Give async task a tick to finish
        await asyncio.sleep(0.05)

        get_resp = await client.get(f"/api/audits/{aid}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["status"] == "complete"
        assert len(data["claims"]) == 1
        assert data["claims"][0]["judgment"]["label"] == "Supported"
        assert data["claims"][0]["judgment"]["evidence_ids"] == ["e1"]
        assert len(data["claims"][0]["evidence"]) == 1
        assert data["claims"][0]["evidence"][0]["id"] == "e1"
