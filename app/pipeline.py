import asyncio, uuid, json, logging, os, time, threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from .schemas import *
from . import db
from .ingest import ingest, IngestError
from .extract import extract_claims
from .retrieve import retrieve_claim
from .judge import judge_claim
from .serp import SerpApiClient
from .llm import get_provider, LLMError

_AUTO_PROVIDER = object()
_logger = logging.getLogger(__name__)


def _positive_int_env(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


# Extraction caps each audit at eight claims. The semaphore bounds blocking
# work across concurrent audits; short-lived pools avoid stale asyncio-loop
# callbacks when callers create repeated event loops (CLI/tests).
MAX_CLAIM_WORKERS = _positive_int_env("AUDITOR_MAX_CLAIM_WORKERS", 3, 8)
_BLOCKING_SLOTS = threading.BoundedSemaphore(MAX_CLAIM_WORKERS)


def _log_judgment_diagnostic(claim, evidence, judgment):
    if os.getenv("AUDITOR_DIAGNOSTICS", "").lower() not in {"1", "true", "yes", "on"}:
        return
    _logger.info("judgment_diagnostic %s", json.dumps({
        "event": "judgment_complete",
        "claim_id": claim.id,
        "evidence_ids_in": [item.id for item in evidence],
        "evidence_ids_cited": judgment.evidence_ids if judgment else [],
        "label": judgment.label.value if judgment and hasattr(judgment.label, "value") else str(judgment.label) if judgment else None,
        "confidence": judgment.confidence if judgment else None,
    }, ensure_ascii=False))


def _log_stage_diagnostic(audit_id, stage, duration_ms, **fields):
    if os.getenv("AUDITOR_DIAGNOSTICS", "").lower() not in {"1", "true", "yes", "on"}:
        return
    payload = {"event": "audit_stage", "audit_id": audit_id, "stage": stage, "duration_ms": round(duration_ms, 2), **fields}
    _logger.info("audit_stage_diagnostic %s", json.dumps(payload, ensure_ascii=False, default=str))


async def _run_blocking(function, *args):
    """Run blocking work on the dedicated bounded executor, not asyncio's pool."""
    loop = asyncio.get_running_loop()
    def bounded_call():
        with _BLOCKING_SLOTS:
            return function(*args)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="claimlens") as executor:
        return await loop.run_in_executor(executor, bounded_call)


async def _bounded_map(function, items, worker_limit):
    """Map items with a fixed number of async workers, preserving input order."""
    values = list(items)
    if not values:
        return []
    def invoke(value):
        with _BLOCKING_SLOTS:
            return function(value)

    # Submit at most worker_limit futures at once, preserving input order and
    # isolating failures. The process-wide semaphore also bounds overlapping
    # audits, whose per-map pools may otherwise multiply thread counts.
    results = []
    with ThreadPoolExecutor(max_workers=min(worker_limit, len(values)), thread_name_prefix="claimlens-retrieval") as executor:
        for offset in range(0, len(values), min(worker_limit, len(values))):
            batch = values[offset:offset + min(worker_limit, len(values))]
            futures = [executor.submit(invoke, value) for value in batch]
            # Avoid asyncio's concurrent-future callback bridge, which can
            # stall when multiple short-lived event loops are used in-process.
            while not all(future.done() for future in futures):
                await asyncio.sleep(0.005)
            for future in futures:
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(exc)
    return results

class AuditPipeline:
    def __init__(self, serp=None, provider=_AUTO_PROVIDER):
        self.serp = serp or SerpApiClient()
        # Distinguish an omitted provider (production: auto-load Gemini) from
        # an explicit None (tests/offline callers: deterministic fallback).
        if provider is not _AUTO_PROVIDER:
            self.provider = provider
        else:
            try:
                self.provider = get_provider()
            except LLMError:
                self.provider = None

    async def run(self, audit_id, url, on_progress=None):
        audit_started = time.perf_counter()
        stage_durations = {}
        def emit(stage, msg, p):
            if on_progress:
                on_progress(ProgressEvent(audit_id=audit_id, stage=stage, message=msg, progress=p))
        try:
            emit("ingest", "Fetching video metadata and transcript", 0.1)
            stage_started = time.perf_counter()
            metadata, segs = await _run_blocking(ingest, url, self.serp)
            stage_durations["ingest"] = (time.perf_counter() - stage_started) * 1000
            _log_stage_diagnostic(audit_id, "ingest", stage_durations["ingest"], segment_count=len(segs))
            emit("extract", "Extracting timestamped claims", 0.3)
            stage_started = time.perf_counter()
            claims = await _run_blocking(extract_claims, segs, self.provider)
            stage_durations["extract"] = (time.perf_counter() - stage_started) * 1000
            _log_stage_diagnostic(audit_id, "extract", stage_durations["extract"], claim_count=len(claims))

            for claim in claims:
                db.save_claim(claim.id, audit_id, claim.model_dump(mode="json"), "pending")

            retrieval_started = time.perf_counter()
            def retrieve_with_diagnostics(claim):
                claim_diagnostics = {}
                try:
                    result = retrieve_claim(claim, self.serp, claim_diagnostics)
                except TypeError as exc:
                    # Keep compatibility with narrow two-argument test doubles
                    # and integrations written against the original callable.
                    if "positional" not in str(exc):
                        raise
                    result = retrieve_claim(claim, self.serp)
                return result, claim_diagnostics

            retrieval_values = await _bounded_map(
                retrieve_with_diagnostics,
                claims,
                MAX_CLAIM_WORKERS,
            )
            stage_durations["retrieval"] = (time.perf_counter() - retrieval_started) * 1000
            _log_stage_diagnostic(
                audit_id,
                "retrieval",
                stage_durations["retrieval"],
                claim_count=len(claims),
                worker_limit=MAX_CLAIM_WORKERS,
                evidence_count=sum(len(value[0][0]) for value in retrieval_values if not isinstance(value, Exception)),
                serp_live_requests=getattr(self.serp, "request_calls", getattr(self.serp, "live_calls", None)),
                serp_cache_hits=getattr(self.serp, "cache_hits", None),
            )

            results = []
            judgment_started = time.perf_counter()
            for i, (claim, retrieval_value) in enumerate(zip(claims, retrieval_values)):
                if isinstance(retrieval_value, Exception):
                    retrieval = retrieval_value
                    claim_diagnostics = {}
                    result = ClaimResult(claim=claim, state="unavailable", error=str(retrieval))
                else:
                    (evidence, state), claim_diagnostics = retrieval_value
                    _log_stage_diagnostic(
                        audit_id,
                        "claim_retrieval",
                        0,
                        claim_id=claim.id,
                        events=claim_diagnostics.get("events", []),
                    )
                    if state == "failed":
                        result = ClaimResult(claim=claim, evidence=evidence, judgment=None, state="failed", error="Retrieval service failed or unavailable")
                    else:
                        try:
                            judgment = await _run_blocking(judge_claim, claim, evidence, self.provider, metadata)
                            _log_judgment_diagnostic(claim, evidence, judgment)
                            result = ClaimResult(claim=claim, evidence=evidence, judgment=judgment, state="complete")
                        except Exception as exc:
                            result = ClaimResult(claim=claim, state="unavailable", error=str(exc))
                results.append(result)
                if result.state == "unavailable":
                    db.save_claim(claim.id, audit_id, result.model_dump(mode="json"), "unavailable")
                emit("claims", f"Processed claim {i+1} of {len(claims)}", 0.35 + 0.55 * (i + 1) / max(1, len(claims)))
            stage_durations["judgment"] = (time.perf_counter() - judgment_started) * 1000
            _log_stage_diagnostic(audit_id, "judgment", stage_durations["judgment"], claim_count=len(claims))

            counts = {v.value: 0 for v in VerdictLabel}
            for r in results:
                if r.judgment:
                    counts[r.judgment.label.value] += 1
            audit_error = None
            if not results and segs:
                audit_error = "No defensible financial or health claims could be extracted from the video transcript."
            score = AuditScorecard(
                audit_id=audit_id,
                status=AuditStatus.COMPLETE,
                metadata=metadata,
                claims=results,
                summary=AuditSummary(
                    total_claims=len(results),
                    checkable_claims=sum(c.claim.checkable for c in results),
                    risk_flags=sum(len(c.claim.risk_flags) for c in results),
                    verdict_counts=counts
                ),
                error=audit_error
            )
            serialization_started = time.perf_counter()
            payload = score.model_dump(mode="json")
            stage_durations["serialization"] = (time.perf_counter() - serialization_started) * 1000
            db_started = time.perf_counter()
            db.save_audit(audit_id, metadata.video_id, score.status.value, payload)
            stage_durations["database_write"] = (time.perf_counter() - db_started) * 1000
            stage_durations["total"] = (time.perf_counter() - audit_started) * 1000
            _log_stage_diagnostic(audit_id, "serialization", stage_durations["serialization"])
            _log_stage_diagnostic(audit_id, "database_write", stage_durations["database_write"])
            _log_stage_diagnostic(audit_id, "total", stage_durations["total"], stage_durations_ms=stage_durations)
            emit("complete", "Audit complete", 1.0)
            return score
        except IngestError as e:
            score = AuditScorecard(audit_id=audit_id, status=AuditStatus.FAILED, error=str(e))
            db.save_audit(audit_id, "", score.status.value, score.model_dump(mode="json"))
            emit("failed", str(e), 1.0)
            return score
        except Exception as e:
            score = AuditScorecard(audit_id=audit_id, status=AuditStatus.FAILED, error=f"Audit failed unexpectedly: {e}")
            db.save_audit(audit_id, "", score.status.value, score.model_dump(mode="json"))
            emit("failed", str(e), 1.0)
            return score
