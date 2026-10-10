"""Offline synthetic timing comparison for sequential and bounded claim retrieval.

Run with: .venv/bin/python eval/benchmark_pipeline.py
All external services and database writes are replaced with local fakes.
The fixed delays model I/O wait only; this is not a live latency benchmark.
"""

import asyncio
import json
import logging
import sys
import time
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import pipeline
from app.schemas import Claim, Judgment, VerdictLabel, VideoMetadata


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.events = []

    def emit(self, record):
        if record.name == "app.pipeline" and "audit_stage_diagnostic" in record.getMessage():
            raw = record.getMessage().split("audit_stage_diagnostic ", 1)[1]
            self.events.append(json.loads(raw))


def run_case(worker_limit, claims_count=8, io_delay=0.04):
    claims = [Claim(
        id=f"bench-{index}", original_text=f"Synthetic fact {index}.",
        normalized_text=f"Synthetic fact {index}.", start_seconds=index,
        domain="other", checkable=True,
    ) for index in range(claims_count)]

    old_worker_limit = pipeline.MAX_CLAIM_WORKERS
    old_ingest, old_extract = pipeline.ingest, pipeline.extract_claims
    old_retrieve, old_judge = pipeline.retrieve_claim, pipeline.judge_claim
    old_save_claim, old_save_audit = pipeline.db.save_claim, pipeline.db.save_audit
    old_diagnostics = __import__("os").environ.get("AUDITOR_DIAGNOSTICS")
    pipeline.MAX_CLAIM_WORKERS = worker_limit
    pipeline.ingest = lambda url, serp: (VideoMetadata(video_id="synthetic", title="Synthetic", url=url), [])
    pipeline.extract_claims = lambda segments, provider: claims
    pipeline.retrieve_claim = lambda claim, serp: (time.sleep(io_delay) or ([], "complete"))
    pipeline.judge_claim = lambda claim, evidence, provider, metadata: Judgment(
        claim_id=claim.id, label=VerdictLabel.NO_EVIDENCE,
        rationale="Synthetic benchmark contains no evidence.",
    )
    pipeline.db.save_claim = lambda *args, **kwargs: None
    pipeline.db.save_audit = lambda *args, **kwargs: None

    import os
    os.environ["AUDITOR_DIAGNOSTICS"] = "1"
    capture = Capture()
    logger = logging.getLogger("app.pipeline")
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)
    started = time.perf_counter()
    try:
        score = asyncio.run(pipeline.AuditPipeline(serp=SimpleNamespace(), provider=None).run(
            f"benchmark-{worker_limit}", "https://youtu.be/abcdefghijk"
        ))
        total_ms = (time.perf_counter() - started) * 1000
    finally:
        logger.removeHandler(capture)
        pipeline.MAX_CLAIM_WORKERS = old_worker_limit
        pipeline.ingest, pipeline.extract_claims = old_ingest, old_extract
        pipeline.retrieve_claim, pipeline.judge_claim = old_retrieve, old_judge
        pipeline.db.save_claim, pipeline.db.save_audit = old_save_claim, old_save_audit
        if old_diagnostics is None:
            os.environ.pop("AUDITOR_DIAGNOSTICS", None)
        else:
            os.environ["AUDITOR_DIAGNOSTICS"] = old_diagnostics

    durations = {event["stage"]: event["duration_ms"] for event in capture.events}
    return {"workers": worker_limit, "claims": len(score.claims), "total_ms": round(total_ms, 2), "stage_durations_ms": durations}


if __name__ == "__main__":
    print(json.dumps({
        "benchmark": "synthetic I/O wait comparison; not live latency evidence",
        "sequential": run_case(1),
        "bounded_concurrent": run_case(min(3, pipeline.MAX_CLAIM_WORKERS)),
    }, indent=2))
