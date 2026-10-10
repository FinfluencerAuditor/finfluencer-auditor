"""Offline tests for bounded claim retrieval and SerpApi single-flight caching."""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app import pipeline
from app.schemas import Claim, Judgment, VerdictLabel, VideoMetadata
from app.serp import SerpApiClient


def _claims(count=6):
    return [Claim(
        id=f"claim-{index}", original_text=f"Claim {index} is a test fact.",
        normalized_text=f"Claim {index} is a test fact.", start_seconds=index,
        domain="other", checkable=True,
    ) for index in range(count)]


def test_pipeline_retrieves_concurrently_with_stable_order_and_isolated_failure(monkeypatch):
    monkeypatch.setattr(pipeline.db, "save_claim", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.db, "save_audit", lambda *args, **kwargs: None)
    claims = _claims()
    monkeypatch.setattr(pipeline, "ingest", lambda url, serp: (
        VideoMetadata(video_id="offline-test", title="Offline", url=url), []
    ))
    monkeypatch.setattr(pipeline, "extract_claims", lambda segments, provider: claims)

    lock = threading.Lock()
    active = 0
    peak = 0

    def retrieve(claim, serp):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.015)
            if claim.id == "claim-2":
                raise TimeoutError("synthetic claim timeout")
            return [], "complete"
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(pipeline, "retrieve_claim", retrieve)
    monkeypatch.setattr(pipeline, "judge_claim", lambda claim, evidence, provider, metadata: Judgment(
        claim_id=claim.id, label=VerdictLabel.NO_EVIDENCE, rationale="Synthetic empty evidence.",
    ))

    score = asyncio.run(asyncio.wait_for(pipeline.AuditPipeline(serp=object(), provider=None).run(
        "offline-audit", "https://youtu.be/abcdefghijk"
    ), timeout=3))

    assert [result.claim.id for result in score.claims] == [claim.id for claim in claims]
    assert [result.state for result in score.claims] == ["complete", "complete", "unavailable", "complete", "complete", "complete"]
    assert peak <= pipeline.MAX_CLAIM_WORKERS
    assert peak > 1


def test_serp_cache_hit_skips_request(monkeypatch):
    cache = {}
    monkeypatch.setattr("app.serp.db.cache_get", lambda key: cache.get(key))
    monkeypatch.setattr("app.serp.db.cache_put", lambda key, value: cache.__setitem__(key, value))
    requests = []

    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"organic_results": []}

    def fake_get(*args, **kwargs):
        requests.append(kwargs)
        return Response()

    monkeypatch.setattr("app.serp.requests.get", fake_get)
    client = SerpApiClient(api_key="offline-test-key", demo_mode=False, retries=0)
    first = client.search("google", q="unique offline cache test")
    second = client.search("google", q="unique offline cache test")
    assert first == second
    assert len(requests) == 1
    assert client.cache_hits == 1


def test_simultaneous_duplicate_serp_search_is_single_flight(monkeypatch):
    cache = {}
    cache_lock = threading.Lock()

    def cache_get(key):
        with cache_lock:
            return cache.get(key)

    def cache_put(key, value):
        with cache_lock:
            cache[key] = value

    monkeypatch.setattr("app.serp.db.cache_get", cache_get)
    monkeypatch.setattr("app.serp.db.cache_put", cache_put)
    calls = []

    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"organic_results": [{"title": "fixture"}]}

    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        time.sleep(0.02)
        return Response()

    monkeypatch.setattr("app.serp.requests.get", fake_get)
    client = SerpApiClient(api_key="offline-test-key", demo_mode=False, retries=0)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: client.search("google", q="single flight"), range(4)))
    assert len(calls) == 1
    assert all(result == results[0] for result in results)
