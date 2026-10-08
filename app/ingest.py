import re
from urllib.parse import urlparse, parse_qs
from .schemas import VideoMetadata, TranscriptSegment
from .serp import SerpApiClient, SerpApiError
class IngestError(RuntimeError): pass

_DESCRIPTION_TEXT_KEYS = ("text", "simpleText", "content", "description", "snippet", "value")

def _description_text(value) -> str:
    """Extract human-readable description text from SerpApi's rich fields.

    YouTube metadata can expose descriptions as a string or as a rich-text
    object (for example ``{"runs": [{"text": "..."}]}``).  Only known text
    fields are traversed; arbitrary objects are intentionally not serialized.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        parts = [_description_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in _DESCRIPTION_TEXT_KEYS:
            if key in value:
                text = _description_text(value[key])
                if text:
                    return text
        for key in ("runs", "items", "contents", "parts"):
            if key in value:
                text = _description_text(value[key])
                if text:
                    return text
    return ""

def parse_video_id(url: str) -> str:
    p=urlparse(url); host=p.netloc.lower().split(":")[0]; vid=""
    if host in {"youtu.be","www.youtu.be"}: vid=p.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        vid=parse_qs(p.query).get("v",[""])[0]
        if not vid and p.path.startswith(("/shorts/","/live/")): vid=p.path.split("/")[2] if len(p.path.split("/"))>2 else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}",vid): raise IngestError("A valid public YouTube URL is required")
    return vid
def _seconds(item,key,fallback=0):
    value = item.get(key)
    if value is not None:
        try:
            value = float(value)
            return value / 1000 if key.endswith("_ms") else value
        except (TypeError, ValueError):
            pass
    try:
        parts=[float(x) for x in item.get("start_time_text","").split(":")]; return sum(v*60**i for i,v in enumerate(reversed(parts)))
    except Exception:return fallback

def _segment_text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("snippet", "text", "simpleText", "content"):
            if key in value:
                text = _description_text(value[key])
                if text:
                    return text.strip()
        if "runs" in value:
            return _description_text(value["runs"]).strip()
    return ""

def normalize_transcript(response):
    """Convert supported SerpApi transcript shapes to timestamped segments."""
    raw = response.get("transcript") if isinstance(response, dict) else response
    if isinstance(response, dict) and not raw:
        raw = response.get("segments") or response.get("items")
    if isinstance(raw, dict):
        raw = raw.get("transcript") or raw.get("segments") or raw.get("items") or []
    if not isinstance(raw, list):
        return []
    segments=[]
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        text = _segment_text(item)
        if not text:
            continue
        start = _seconds(item, "start_ms", _seconds(item, "start_seconds", 0))
        duration = _seconds(item, "duration_ms", 0)
        end = _seconds(item, "end_ms", _seconds(item, "end_seconds", start + duration))
        if end < start:
            end = start + max(duration, 0)
        segments.append(TranscriptSegment(index=index, start_seconds=start, end_seconds=end, text_original=text))
    return segments

def ingest(url,serp):
    vid=parse_video_id(url)
    try:
        meta=serp.search("youtube_video",v=vid)
        # Prefer the language-neutral request. Existing language-specific cache entries
        # are checked first so this change does not spend a duplicate live search.
        tr = serp.cached_search("youtube_video_transcript", v=vid)
        if not isinstance(tr, dict):
            tr = None
        if tr is None:
            tr = serp.cached_search("youtube_video_transcript", v=vid, language_code="en")
            if not isinstance(tr, dict):
                tr = None
        if tr is None:
            tr = serp.search("youtube_video_transcript",v=vid)
    except SerpApiError as e: raise IngestError("Transcript unavailable for this video.") from e
    segments = normalize_transcript(tr)
    if not segments: raise IngestError("Transcript unavailable for this video.")
    channel=meta.get("channel",""); channel=channel.get("name","") if isinstance(channel,dict) else str(channel)
    description = _description_text(meta.get("description"))
    language = None
    if isinstance(tr, dict):
        language = tr.get("language_code") or tr.get("language")
        if not language:
            available = tr.get("available_transcripts") or []
            selected = next((item for item in available if isinstance(item, dict) and item.get("selected")), None)
            if selected:
                language = selected.get("language_code") or selected.get("language")
    return VideoMetadata(video_id=vid,title=meta.get("title", ""),channel=channel,published_at=meta.get("published_date"),description=description,language=language,url=url),segments
