import hashlib, json, os, time
import threading
from typing import Any
import requests
from . import db

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class SerpApiError(RuntimeError): pass

def _bounded_env_number(name, default, minimum, maximum, cast):
    try: value=cast(os.getenv(name, default))
    except (TypeError, ValueError): value=cast(default)
    return max(minimum, min(maximum, value))

class SerpApiClient:
    def __init__(self, api_key=None, base_url="https://serpapi.com/search.json", demo_mode=None, timeout=None, retries=None):
        if not os.getenv("SERPAPI_API_KEY"):
            try:
                from dotenv import load_dotenv
                load_dotenv()
            except ImportError:
                pass
        self.api_key=api_key or os.getenv("SERPAPI_API_KEY"); self.base_url=base_url
        self.demo_mode=bool(int(os.getenv("DEMO_MODE","0"))) if demo_mode is None else demo_mode
        self.timeout=timeout if timeout is not None else _bounded_env_number("SERPAPI_TIMEOUT_SECONDS", 20, 1, 60, float)
        self.retries=retries if retries is not None else _bounded_env_number("SERPAPI_RETRIES", 2, 0, 2, int)
        self.live_calls=0; self.cache_hits=0; self.request_calls=0
        self._counter_lock=threading.Lock(); self._key_locks_guard=threading.Lock(); self._key_locks={}; self._search_context=threading.local()
    @staticmethod
    def cache_key(engine: str, params: dict[str,Any]):
        clean={k:v for k,v in params.items() if k not in {"api_key","key"}}
        return hashlib.sha256(json.dumps({"engine":engine,"params":clean},sort_keys=True,default=str).encode()).hexdigest()
    def search(self, engine: str, **params):
        params={k:v for k,v in params.items() if v is not None}; key=self.cache_key(engine,params)
        cached=db.cache_get(key)
        if cached is not None:
            with self._counter_lock: self.cache_hits += 1
            self._search_context.last_search={"engine":engine,"cache_hit":True,"status":"cache_hit"}
            return cached
        # Single-flight per normalized cache key: parallel claims can reuse one
        # in-progress SerpApi lookup instead of issuing duplicate paid calls.
        with self._key_locks_guard:
            key_lock=self._key_locks.setdefault(key,threading.Lock())
        with key_lock:
            cached=db.cache_get(key)
            if cached is not None:
                with self._counter_lock: self.cache_hits += 1
                self._search_context.last_search={"engine":engine,"cache_hit":True,"status":"cache_hit"}
                return cached
            return self._request_and_cache(engine, params, key)

    def _request_and_cache(self, engine, params, key):
        if self.demo_mode:
            self._search_context.last_search={"engine":engine,"cache_hit":False,"status":"demo_miss"}
            raise SerpApiError(f"No demo fixture cached for engine={engine}")
        api_key = self.api_key or os.getenv("SERPAPI_API_KEY")
        if not api_key:
            self._search_context.last_search={"engine":engine,"cache_hit":False,"status":"missing_key"}
            raise SerpApiError("SERPAPI_API_KEY is not configured")
        request_params={"engine":engine,"api_key":api_key,**params}
        last=None
        for attempt in range(self.retries+1):
            try:
                with self._counter_lock:
                    self.live_calls += 1; self.request_calls += 1
                response=requests.get(self.base_url,params=request_params,timeout=self.timeout)
                if response.status_code >= 500: raise requests.HTTPError(f"HTTP {response.status_code}")
                response.raise_for_status(); data=response.json()
                if not isinstance(data, dict):
                    raise SerpApiError("SerpApi returned a malformed response object")
                if data.get("error"): raise SerpApiError(str(data["error"]))
                db.cache_put(key,data)
                self._search_context.last_search={"engine":engine,"cache_hit":False,"status":"live_success"}
                return data
            except (requests.RequestException, ValueError, SerpApiError) as exc:
                last=exc
                if isinstance(exc, SerpApiError) and not str(exc).startswith("HTTP"): break
                if attempt < self.retries: time.sleep(0.25*(2**attempt))
        self._search_context.last_search={"engine":engine,"cache_hit":False,"status":"error","error_type":type(last).__name__ if last else "unknown"}
        raise SerpApiError(f"SerpApi request failed: {last}") from last

    @property
    def last_search(self):
        return getattr(self._search_context, "last_search", {})

    def cached_search(self, engine: str, **params):
        """Return a cached response without making a live request."""
        params={k:v for k,v in params.items() if v is not None}
        return db.cache_get(self.cache_key(engine,params))
