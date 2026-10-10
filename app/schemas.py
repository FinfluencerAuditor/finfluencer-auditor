from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator

class VerdictLabel(str, Enum):
    SUPPORTED = "Supported"
    CONTRADICTED = "Contradicted"
    MIXED = "Mixed"
    NO_EVIDENCE = "No evidence found"
    UNVERIFIABLE = "Unverifiable"

class AuditStatus(str, Enum):
    PENDING = "pending"; RUNNING = "running"; COMPLETE = "complete"; FAILED = "failed"

class TranscriptSegment(BaseModel):
    index: int | None = None
    start_seconds: float = Field(ge=0); end_seconds: float = Field(ge=0)
    text_original: str; text_english: str | None = None

class VideoMetadata(BaseModel):
    video_id: str; title: str = ""; channel: str = ""; published_at: str | None = None
    description: str = ""; language: str | None = None; url: str

class RiskFlag(BaseModel):
    phrase: str; category: str = "risk_language"

class Claim(BaseModel):
    id: str | None = None
    original_text: str = ""
    normalized_text: str = ""
    # Backward-compatible names used by the existing scorecard and Person B interfaces.
    quote_original: str = ""
    claim_english: str = ""
    start_seconds: float = Field(ge=0); end_seconds: float | None = Field(default=None, ge=0)
    domain: str = "other"; claim_type: str = "verifiable_fact"; entities: dict[str, Any] = {}
    risk_flags: list[RiskFlag] = []; checkable: bool = True; priority: float = 0
    context: str = ""; numeric_info: list[dict[str, Any]] = []
    source_segment_indices: list[int] = []
    normalization_status: str = "unvalidated"

    @model_validator(mode="after")
    def synchronize_text_fields(self):
        if not self.original_text:
            self.original_text = self.quote_original
        if not self.quote_original:
            self.quote_original = self.original_text
        if not self.normalized_text:
            self.normalized_text = self.claim_english
        if not self.claim_english:
            self.claim_english = self.normalized_text
        return self

class Evidence(BaseModel):
    id: str; engine: str; title: str; source: str = ""; tier: int = Field(ge=1, le=3)
    date: str | None = None; snippet: str = ""; url: str; retrieved_at: str | None = None
    metadata: dict[str, Any] = {}

class Judgment(BaseModel):
    claim_id: str; label: VerdictLabel; confidence: str = "Low"; rationale: str
    evidence_ids: list[str] = []
    analysis_mode: str = "deterministic"

class ClaimResult(BaseModel):
    claim: Claim; evidence: list[Evidence] = []; judgment: Judgment | None = None
    state: str = "pending"; error: str | None = None

class AuditSummary(BaseModel):
    total_claims: int = 0; checkable_claims: int = 0; risk_flags: int = 0
    verdict_counts: dict[str, int] = {}

class AuditScorecard(BaseModel):
    audit_id: str; status: AuditStatus; metadata: VideoMetadata | None = None
    claims: list[ClaimResult] = []; summary: AuditSummary = AuditSummary(); error: str | None = None

class ProgressEvent(BaseModel):
    audit_id: str; stage: str; message: str; progress: float = Field(ge=0, le=1)

class AuditRequest(BaseModel):
    url: str
    @field_validator("url")
    @classmethod
    def nonempty(cls, v):
        if not v.strip(): raise ValueError("YouTube URL is required")
        return v.strip()
