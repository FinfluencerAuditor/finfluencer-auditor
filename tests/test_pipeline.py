import asyncio
from app import pipeline
from app.schemas import VideoMetadata, TranscriptSegment
from app.extract import ExtractedClaims
from app.schemas import Claim

class Provider:
    def structured(self, operation, prompt, schema):
        return ExtractedClaims(claims=[Claim(original_text="The Nifty 50 fell 10 percent.",normalized_text="The Nifty 50 fell 10 percent.",start_seconds=0,end_seconds=2,domain="finance",claim_type="statistic",checkable=True)])

def test_pipeline_progress_and_claim_failure_isolation(monkeypatch):
    monkeypatch.setattr(pipeline.db, "save_claim", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.db, "save_audit", lambda *args, **kwargs: None)
    async def direct_to_thread(function, *args):
        return function(*args)
    monkeypatch.setattr(pipeline.asyncio, "to_thread", direct_to_thread)
    monkeypatch.setattr(pipeline, "ingest", lambda url, serp: (VideoMetadata(video_id="x",title="t",url=url), [TranscriptSegment(index=0,start_seconds=0,end_seconds=2,text_original="Nifty 50 fell 10 percent.")]))
    monkeypatch.setattr(pipeline, "retrieve_claim", lambda claim, serp: ([], "not_implemented"))
    events=[]
    score=asyncio.run(pipeline.AuditPipeline(serp=object(),provider=Provider()).run("audit-test","https://youtu.be/abcdefghijk",events.append))
    assert score.status.value=="complete" and len(score.claims)==1
    assert [event.stage for event in events]==["ingest","extract","claims","complete"]
    assert events[-1].progress==1
