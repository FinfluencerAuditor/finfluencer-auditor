from unittest.mock import Mock
from app import db
from app.ingest import parse_video_id,IngestError,ingest,_description_text,normalize_transcript
from app.schemas import TranscriptSegment
from app.extract import chunk_transcript,extract_claims
from app.serp import SerpApiClient,SerpApiError
from app.llm import LLMError
from app.extract import ExtractedClaims
def test_url_and_timestamp_parsing():
    assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")=="dQw4w9WgXcQ"
    assert parse_video_id("https://youtu.be/dQw4w9WgXcQ?t=3")=="dQw4w9WgXcQ"
    try: parse_video_id("https://example.com/nope")
    except IngestError: pass
    else: assert False
    serp=Mock();serp.search.side_effect=[{"title":"x","channel":{"name":"c"},"description":{"text":"A real video description","runs":[{"text":"ignored after text"}]}},{"transcript":[{"start_ms":1200,"end_ms":2500,"snippet":"A stock claim"}]}]
    _,segments=ingest("https://youtu.be/dQw4w9WgXcQ",serp);assert segments[0].start_seconds==1.2
def test_description_rich_response_is_normalized():
    assert _description_text("plain description")=="plain description"
    assert _description_text({"runs":[{"text":"Part one"},{"text":"Part two"}]})=="Part one\nPart two"
    assert _description_text([{"simpleText":"One"},{"content":"Two"}])=="One\nTwo"
    assert _description_text(None)==""
    serp=Mock();serp.search.side_effect=[{"title":"Finance video","channel":{"name":"Channel"},"description":{"runs":[{"text":"Description from SerpApi"}]}},{"transcript":[{"start_ms":2086,"end_ms":3492,"snippet":"The first timestamped line."},{"start_ms":3517,"end_ms":4517,"snippet":"The second timestamped line."}]}]
    metadata,segments=ingest("https://www.youtube.com/watch?v=LO-gNRiK0Aw",serp)
    assert metadata.description=="Description from SerpApi"
    assert isinstance(metadata.description,str)
    assert len(segments)==2 and segments[0].start_seconds==2.086
def test_multilingual_and_malformed_transcripts_normalize_without_translation():
    hindi=normalize_transcript({"language":"hi","transcript":[{"start_ms":0,"end_ms":1200,"snippet":"यह हिंदी दावा है।"}]})
    mixed=normalize_transcript({"transcript":[{"start_ms":1200,"duration_ms":800,"snippet":{"runs":[{"text":"Market correction में गिरावट"}]}}]})
    assert hindi[0].text_original=="यह हिंदी दावा है।" and hindi[0].start_seconds==0
    assert mixed[0].text_original=="Market correction में गिरावट" and mixed[0].end_seconds==2
    assert normalize_transcript({"transcript": {"unexpected": "shape"}})==[]
    assert normalize_transcript({"transcript": [None, {}, {"start_ms": 0, "snippet": ""}]})==[]
    serp=Mock();serp.search.side_effect=[{"title":"Hindi","channel":{"name":"Channel"}},{"transcript":[{"start_ms":0,"end_ms":1000,"snippet":"हिंदी"}],"available_transcripts":[{"language_code":"hi","selected":True}]}]
    serp.cached_search.return_value=None
    metadata,_=ingest("https://youtu.be/dQw4w9WgXcQ",serp)
    assert metadata.language=="hi"
def test_missing_transcript_is_friendly():
    serp=Mock();serp.search.return_value={"title":"x","channel":{"name":"c"}}
    serp.cached_search.return_value=None
    try: ingest("https://youtu.be/dQw4w9WgXcQ",serp)
    except IngestError as exc: assert str(exc)=="Transcript unavailable for this video."
    else: assert False
def test_chunk_dedupe_limits_and_risk():
    seg=[TranscriptSegment(start_seconds=i,end_seconds=i+10,text_original=f"This guaranteed stock return claim number {i}") for i in range(0,1000,10)]
    assert chunk_transcript(seg); claims=extract_claims(seg)
    assert len([c for c in claims if c.checkable])<=8;assert all(c.start_seconds>=0 for c in claims);assert any(c.risk_flags for c in claims)
def test_db_cache_persists():
    db.cache_put("k",{"value":1});assert db.cache_get("k")=={"value":1};db.save_audit("a","v","pending",{"x":1});assert db.load_audit("a")["status"]=="pending"
def test_serp_cache_hit_and_demo_miss():
    c=SerpApiClient(api_key="secret",demo_mode=False);db.cache_put(c.cache_key("google",{"q":"x"}),{"organic_results":[]});assert c.search("google",q="x")["organic_results"]==[] and c.live_calls==0
    try: SerpApiClient(demo_mode=True).search("google",q="never-cached")
    except SerpApiError as e: assert "fixture" in str(e)
    else: assert False
