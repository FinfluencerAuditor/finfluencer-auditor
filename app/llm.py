import hashlib
import json
import os
from typing import Protocol

from pydantic import BaseModel, ValidationError

from . import db

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    def structured(self, operation: str, prompt: str, schema: type[BaseModel]) -> BaseModel: ...


def _gemini_response_schema(model):
    """Minimal strict wire schema; persistence uses the richer app models."""
    if model.__name__ == "ExtractedClaims":
        risk = {
            "type": "object",
            "properties": {"phrase": {"type": "string"}, "category": {"type": "string"}},
            "required": ["phrase", "category"],
        }
        numeric = {
            "type": "object",
            "properties": {
                "original": {"type": "string"},
                "value": {"type": "string"},
                "unit": {"type": "string"},
                "context": {"type": "string"},
            },
            "required": ["original", "value", "unit", "context"],
        }
        claim = {
            "type": "object",
            "properties": {
                "original_text": {"type": "string"},
                "normalized_text": {"type": "string"},
                "start_seconds": {"type": "number"},
                "end_seconds": {"type": "number"},
                "domain": {"type": "string", "enum": ["finance", "health", "other"]},
                "claim_type": {"type": "string", "enum": ["verifiable_fact", "prediction", "opinion", "advice", "historical_fact", "statistic", "comparison", "other"]},
                "entities": {"type": "array", "items": {"type": "string"}},
                "numeric_info": {"type": "array", "items": numeric},
                "risk_flags": {"type": "array", "items": risk},
                "checkable": {"type": "boolean"},
                "source_segment_indices": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["original_text", "normalized_text", "start_seconds", "end_seconds", "domain", "claim_type", "entities", "numeric_info", "risk_flags", "checkable", "source_segment_indices"],
        }
        return {"type": "object", "properties": {"claims": {"type": "array", "items": claim}}, "required": ["claims"]}
    if model.__name__ == "NormalizedClaims":
        item = {
            "type": "object",
            "properties": {
                "index": {"type": "integer"},
                "normalized_text": {"type": "string"},
                "domain": {"type": "string", "enum": ["finance", "health", "other"]},
                "claim_type": {"type": "string", "enum": ["verifiable_fact", "prediction", "opinion", "advice", "historical_fact", "statistic", "comparison", "other"]},
                "entities": {"type": "array", "items": {"type": "string"}},
                "checkable": {"type": "boolean"},
            },
            "required": ["index", "normalized_text", "domain", "claim_type", "entities", "checkable"],
        }
    if model.__name__ == "LLMVerdictSchema":
        return {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "enum": ["Supported", "Contradicted", "Mixed", "No evidence found", "Unverifiable"],
                },
                "confidence": {
                    "type": "string",
                    "enum": ["Low", "Medium", "High"],
                },
                "rationale": {"type": "string"},
                "evidence_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["label", "confidence", "rationale", "evidence_ids"],
        }
    return model.model_json_schema()


def _coerce_wire_value(model, value):
    if not isinstance(value, dict):
        return value
    if model.__name__ in {"ExtractedClaims", "NormalizedClaims"}:
        for claim in value.get("claims", []):
            if isinstance(claim, dict) and isinstance(claim.get("entities"), list):
                claim["entities"] = {"mentions": claim["entities"]}
    return value


def _parse_structured(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Gemini returned an empty structured response")
    return json.loads(text)


class GeminiProvider:
    """The project's only LLM provider, using Google's official Gemini SDK."""

    def __init__(self, api_key=None, model=None, timeout=120, client=None):
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        if not self.api_key and client is None:
            raise LLMError("GEMINI_API_KEY is not configured")
        if client is None and genai is None:
            raise LLMError("The google-genai package is not installed")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        self.timeout = timeout
        self.client = client or genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=int(self.timeout * 1000)),
        )

    def _call(self, prompt, schema):
        import time
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                config = types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=_gemini_response_schema(schema),
                )
                response = self.client.models.generate_content(model=self.model, contents=prompt, config=config)
                content = getattr(response, "text", None)
                if not content and getattr(response, "parsed", None) is not None:
                    content = json.dumps(response.parsed, ensure_ascii=False)
                if not content:
                    raise LLMError("Gemini returned an empty structured response")
                return content
            except LLMError:
                raise
            except Exception as exc:
                err_msg = str(exc)
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "[REDACTED]")
                is_quota = "RESOURCE_EXHAUSTED" in err_msg or ("429" in err_msg and "quota" in err_msg.lower())
                is_transient = "503" in err_msg or "UNAVAILABLE" in err_msg or "500" in err_msg or "temporary" in err_msg.lower()
                if attempt < max_retries and is_transient and not is_quota:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise LLMError(f"Gemini request failed ({type(exc).__name__}): {err_msg}") from exc

    def structured(self, operation, prompt, schema):
        key = hashlib.sha256(("gemini" + self.model + operation + prompt + schema.__name__).encode()).hexdigest()
        cached = db.cache_get(key, "llm_cache")
        if cached is not None:
            try:
                return schema.model_validate(cached)
            except ValidationError:
                pass
        try:
            payload = _coerce_wire_value(schema, _parse_structured(self._call(prompt, schema)))
            value = schema.model_validate(payload)
        except LLMError:
            raise
        except (ValueError, ValidationError) as first:
            try:
                repair = prompt + "\nReturn only valid JSON matching the supplied response schema. Do not add commentary or markdown."
                payload = _coerce_wire_value(schema, _parse_structured(self._call(repair, schema)))
                value = schema.model_validate(payload)
            except Exception as exc:
                raise LLMError(f"Malformed structured Gemini output: {type(exc).__name__}") from first
        db.cache_put(key, value.model_dump(mode="json"), "llm_cache")
        return value


def get_provider():
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    if provider != "gemini":
        raise LLMError(f"Unsupported LLM_PROVIDER: {provider}; only gemini is supported")
    timeout = _bounded_timeout(os.getenv("GEMINI_TIMEOUT_SECONDS", "120"))
    return GeminiProvider(timeout=timeout)


def _bounded_timeout(raw):
    try:
        return max(1, min(300, int(raw)))
    except (TypeError, ValueError):
        return 120
