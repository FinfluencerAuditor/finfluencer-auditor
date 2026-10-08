import asyncio, uuid
from .schemas import *
from . import db
from .ingest import ingest,IngestError
from .extract import extract_claims
from .retrieve import retrieve_claim
from .judge import judge_claim
from .serp import SerpApiClient
from .llm import get_provider, LLMError
class AuditPipeline:
    def __init__(self,serp=None,provider=None):
        self.serp=serp or SerpApiClient()
        if provider is not None:
            self.provider=provider
        else:
            try:
                self.provider=get_provider()
            except LLMError:
                self.provider=None
    async def run(self,audit_id,url,on_progress=None):
        def emit(stage,msg,p):
            if on_progress:on_progress(ProgressEvent(audit_id=audit_id,stage=stage,message=msg,progress=p))
        try:
            emit("ingest","Fetching video metadata and transcript",.1); metadata,segs=ingest(url,self.serp)
            emit("extract","Extracting timestamped claims",.3); claims=extract_claims(segs,self.provider)
            results=[]
            for i,claim in enumerate(claims):
                db.save_claim(claim.id,audit_id,claim.model_dump(mode="json"),"pending")
                try:
                    evidence,state=await asyncio.to_thread(retrieve_claim,claim,self.serp); judgment=None
                    if state=="not_implemented": judgment=judge_claim(claim,evidence,self.provider); judgment=judgment[0] if isinstance(judgment,tuple) else judgment
                    else: judgment=await asyncio.to_thread(judge_claim,claim,evidence,self.provider)
                    results.append(ClaimResult(claim=claim,evidence=evidence,judgment=judgment,state=state if state!="not_implemented" else ("complete" if judgment else "not_implemented")))
                except Exception as e: results.append(ClaimResult(claim=claim,state="unavailable",error=str(e)))
                emit("claims",f"Processed claim {i+1} of {len(claims)}",.35+.55*(i+1)/max(1,len(claims)))
            counts={v.value:0 for v in VerdictLabel}
            for r in results:
                if r.judgment:counts[r.judgment.label.value]+=1
            score=AuditScorecard(audit_id=audit_id,status=AuditStatus.COMPLETE,metadata=metadata,claims=results,summary=AuditSummary(total_claims=len(results),checkable_claims=sum(c.claim.checkable for c in results),risk_flags=sum(len(c.claim.risk_flags) for c in results),verdict_counts=counts))
            db.save_audit(audit_id,metadata.video_id,score.status.value,score.model_dump(mode="json"));emit("complete","Audit complete",1);return score
        except IngestError as e:
            score=AuditScorecard(audit_id=audit_id,status=AuditStatus.FAILED,error=str(e));db.save_audit(audit_id,"",score.status.value,score.model_dump(mode="json"));emit("failed",str(e),1);return score
