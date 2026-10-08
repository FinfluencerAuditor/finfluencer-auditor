import asyncio, json, os, uuid
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .schemas import AuditRequest
from . import db
from .pipeline import AuditPipeline
app=FastAPI(title="Finfluencer & Health-Claim Auditor")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
queues={}; tasks={}
@app.get("/api/health")
def health(): return {"status":"ok","llm_provider":os.getenv("LLM_PROVIDER","gemini"),"demo_mode":bool(int(os.getenv("DEMO_MODE","0")))}
@app.post("/api/audits",status_code=202)
async def submit(req:AuditRequest):
    aid=str(uuid.uuid4());queues[aid]=asyncio.Queue();db.save_audit(aid,"","pending",{"audit_id":aid,"status":"pending"})
    async def work():
        def progress(event): queues[aid].put_nowait(event.model_dump(mode="json"))
        score=await AuditPipeline().run(aid,req.url,progress); tasks[aid]=score
    asyncio.create_task(work());return {"audit_id":aid,"status":"pending"}
@app.get("/api/audits/{audit_id}")
def get_audit(audit_id):
    if audit_id in tasks:return tasks[audit_id]
    row=db.load_audit(audit_id)
    if not row:raise HTTPException(404,"Audit not found")
    return json.loads(row["payload_json"])
@app.get("/api/audits/{audit_id}/events")
async def events(audit_id):
    if audit_id not in queues:raise HTTPException(404,"Audit not found")
    async def stream():
        while True:
            item=await queues[audit_id].get();yield f"data: {json.dumps(item)}\n\n"
            if item.get("stage") in {"complete","failed"}:break
    return StreamingResponse(stream(),media_type="text/event-stream")
@app.get("/api/audits/{audit_id}/export")
def export(audit_id,format="json"):
    score=get_audit(audit_id)
    if format=="json":return JSONResponse(score)
    if format!="md":raise HTTPException(400,"format must be json or md")
    lines=[f"# Audit {audit_id}","",f"Status: {score.get('status')}",""]
    for r in score.get("claims",[]):lines += [f"## {r['claim']['claim_english']}",f"- Verdict: {(r.get('judgment') or {}).get('label','Unavailable')}",f"- Timestamp: {r['claim']['start_seconds']}s",""]
    return StreamingResponse(iter(["\n".join(lines)]),media_type="text/markdown",headers={"Content-Disposition":f"attachment; filename={audit_id}.md"})

if os.path.isdir("web"):
    app.mount("/", StaticFiles(directory="web", html=True), name="web")
