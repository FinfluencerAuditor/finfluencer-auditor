import hashlib, json, os, time
from typing import Any
import requests
from . import db

class SerpApiError(RuntimeError): pass
class SerpApiClient:
    def __init__(self, api_key=None, base_url="https://serpapi.com/search.json", demo_mode=None, timeout=20, retries=2):
        self.api_key=api_key or os.getenv("SERPAPI_API_KEY"); self.base_url=base_url
        self.demo_mode=bool(int(os.getenv("DEMO_MODE","0"))) if demo_mode is None else demo_mode
        self.timeout=timeout; self.retries=retries; self.live_calls=0
    @staticmethod
    def cache_key(engine: str, params: dict[str,Any]):
        clean={k:v for k,v in params.items() if k not in {"api_key","key"}}
        return hashlib.sha256(json.dumps({"engine":engine,"params":clean},sort_keys=True,default=str).encode()).hexdigest()
    def search(self, engine: str, **params):
        params={k:v for k,v in params.items() if v is not None}; key=self.cache_key(engine,params)
        cached=db.cache_get(key)
        if cached is not None: return cached
        if self.demo_mode:
            raise SerpApiError(f"No demo fixture cached for engine={engine}")
        if not self.api_key: raise SerpApiError("SERPAPI_API_KEY is not configured")
        request_params={"engine":engine,"api_key":self.api_key,**params}
        last=None
        for attempt in range(self.retries+1):
            try:
                self.live_calls += 1; response=requests.get(self.base_url,params=request_params,timeout=self.timeout)
                if response.status_code >= 500: raise requests.HTTPError(f"HTTP {response.status_code}")
                response.raise_for_status(); data=response.json()
                if data.get("error"): raise SerpApiError(str(data["error"]))
                db.cache_put(key,data); return data
            except (requests.RequestException, ValueError, SerpApiError) as exc:
                last=exc
                if isinstance(exc, SerpApiError) and not str(exc).startswith("HTTP"): break
                if attempt < self.retries: time.sleep(0.25*(2**attempt))
        raise SerpApiError(f"SerpApi request failed: {last}") from last

    def cached_search(self, engine: str, **params):
        """Return a cached response without making a live request."""
        params={k:v for k,v in params.items() if v is not None}
        return db.cache_get(self.cache_key(engine,params))
