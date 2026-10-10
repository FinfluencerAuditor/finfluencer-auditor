"""Comprehensive automated tests for transcript ingestion, claim extraction, fallback, and quota recovery."""

import pytest
from unittest.mock import Mock
from app.extract import (
    ExtractedClaims,
    NormalizedClaim,
    NormalizedClaims,
    chunk_transcript,
    extract_claims,
    _fallback,
)
from app.ingest import IngestError, ingest, normalize_transcript
from app.llm import GeminiProvider, LLMError
from app.pipeline import AuditPipeline
from app.schemas import (
    AuditStatus,
    Claim,
    TranscriptSegment,
    VideoMetadata,
)
from app.serp import SerpApiError


# =========================================================================
# 1. Transcript Ingestion (Successful, Empty, Unexpected Shapes)
# =========================================================================

def test_successful_transcript_multiple_segments():
    raw_data = {
        "transcript": [
            {"start_ms": 0, "end_ms": 2500, "snippet": "Welcome to market analysis."},
            {"start_ms": 2500, "end_ms": 5000, "snippet": "Nifty 50 is trading at 24500."},
            {"start_ms": 5000, "end_ms": 8000, "snippet": "We expect a consolidation."}
        ]
    }
    segments = normalize_transcript(raw_data)
    assert len(segments) == 3
    assert segments[0].start_seconds == 0.0
    assert segments[0].end_seconds == 2.5
    assert segments[1].text_original == "Nifty 50 is trading at 24500."


def test_empty_and_unexpected_transcript_responses():
    # Empty transcript
    assert normalize_transcript({}) == []
    assert normalize_transcript({"transcript": []}) == []
    assert normalize_transcript(None) == []
    assert normalize_transcript("unexpected_string") == []

    # Unexpected dict structure without segments
    assert normalize_transcript({"other_field": 123}) == []

    # Ingest should raise IngestError on empty segments
    mock_serp = Mock()
    mock_serp.search.return_value = {"title": "Test Video"}
    mock_serp.cached_search.return_value = {"transcript": []}
    with pytest.raises(IngestError, match="Transcript unavailable"):
        ingest("https://www.youtube.com/watch?v=12345678901", mock_serp)


# =========================================================================
# 2. Hindi and Hinglish Claim Extraction
# =========================================================================

def test_hindi_hinglish_extraction_with_provider():
    segments = [
        TranscriptSegment(index=0, start_seconds=0.0, end_seconds=3.0, text_original="निफ्टी 50 10% गिरा है।"),
        TranscriptSegment(index=1, start_seconds=3.0, end_seconds=6.0, text_original="Market correction me portfolio 20% down hua.")
    ]

    class MockProvider:
        def structured(self, operation, prompt, schema):
            if operation == "extract_v2":
                return ExtractedClaims(claims=[
                    Claim(
                        original_text="निफ्टी 50 10% गिरा है।",
                        normalized_text="The Nifty 50 fell 10%.",
                        start_seconds=0.0,
                        end_seconds=3.0,
                        domain="finance",
                        claim_type="statistic",
                        checkable=True,
                        numeric_info=[{"original": "10%", "value": 10.0, "unit": "%"}],
                        entities={"finance_terms": ["Nifty 50"]}
                    ),
                    Claim(
                        original_text="Market correction me portfolio 20% down hua.",
                        normalized_text="The portfolio fell 20% during the market correction.",
                        start_seconds=3.0,
                        end_seconds=6.0,
                        domain="finance",
                        claim_type="statistic",
                        checkable=True,
                        numeric_info=[{"original": "20%", "value": 20.0, "unit": "%"}],
                        entities={"finance_terms": ["portfolio"]}
                    )
                ])
            return ExtractedClaims()

    claims = extract_claims(segments, MockProvider())
    assert len(claims) == 2
    assert all(c.normalization_status == "validated" for c in claims)
    texts = [c.normalized_text for c in claims]
    assert any("Nifty 50" in t for t in texts)
    assert any("portfolio" in t for t in texts)


# =========================================================================
# 3. Gemini Returns Empty Claims List -> Fallback Triggered
# =========================================================================

def test_gemini_empty_claims_triggers_fallback():
    segments = [
        TranscriptSegment(index=0, start_seconds=10.0, end_seconds=15.0, text_original="Reliance Q3 revenue increased by 15%."),
        TranscriptSegment(index=1, start_seconds=15.0, end_seconds=20.0, text_original="Operating margins improved to 22%.")
    ]

    class EmptyProvider:
        def structured(self, operation, prompt, schema):
            if operation == "extract_v2":
                # Return valid schema with 0 claims
                return ExtractedClaims(claims=[])
            return ExtractedClaims()

    claims = extract_claims(segments, EmptyProvider())
    # Should fall back to deterministic extraction
    assert len(claims) >= 1
    assert any("Reliance" in c.original_text or "revenue" in c.original_text for c in claims)


# =========================================================================
# 4. Gemini Raises LLMError (503 / 429) -> Graceful Fallback
# =========================================================================

def test_gemini_llm_error_graceful_fallback():
    segments = [
        TranscriptSegment(index=0, start_seconds=5.0, end_seconds=9.0, text_original="Tata Motors P/E ratio is currently 16.2."),
        TranscriptSegment(index=1, start_seconds=9.0, end_seconds=14.0, text_original="The stock price rose 5% yesterday.")
    ]

    class FailingProvider:
        def structured(self, operation, prompt, schema):
            raise LLMError("Gemini request failed (ServerError): 503 UNAVAILABLE")

    claims = extract_claims(segments, FailingProvider())
    assert len(claims) >= 1
    assert any(c.domain == "finance" for c in claims)
    assert claims[0].start_seconds >= 5.0


# =========================================================================
# 5. Deterministic Fallback Timestamps and Segment Indices
# =========================================================================

def test_deterministic_fallback_timestamps_and_segment_indices():
    segments = [
        TranscriptSegment(index=10, start_seconds=45.0, end_seconds=48.0, text_original="The 10-year bond yield"),
        TranscriptSegment(index=11, start_seconds=48.0, end_seconds=52.0, text_original="stands at 7.15 percent."),
    ]
    fb = _fallback(segments)
    assert len(fb.claims) >= 1
    claim = fb.claims[0]
    assert claim.start_seconds == 45.0
    assert claim.end_seconds == 52.0
    assert 10 in claim.source_segment_indices
    assert 11 in claim.source_segment_indices


# =========================================================================
# 6. Deduplication Preserves Distinct Claims
# =========================================================================

def test_deduplication_preserves_distinct_claims():
    segments = [
        TranscriptSegment(index=0, start_seconds=0.0, end_seconds=5.0, text_original="Nifty 50 fell 5 percent in January."),
        TranscriptSegment(index=1, start_seconds=10.0, end_seconds=15.0, text_original="Nifty 50 fell 5 percent in January."), # Duplicate
        TranscriptSegment(index=2, start_seconds=20.0, end_seconds=25.0, text_original="Sensex dropped 3 percent in February."), # Distinct
    ]

    class MockProvider:
        def structured(self, operation, prompt, schema):
            return ExtractedClaims(claims=[
                Claim(
                    original_text="Nifty 50 fell 5 percent in January.",
                    normalized_text="Nifty 50 fell 5 percent in January.",
                    start_seconds=0.0,
                    end_seconds=5.0,
                    domain="finance",
                    claim_type="statistic",
                    checkable=True
                ),
                Claim(
                    original_text="Nifty 50 fell 5 percent in January.",
                    normalized_text="Nifty 50 fell 5 percent in January.",
                    start_seconds=10.0,
                    end_seconds=15.0,
                    domain="finance",
                    claim_type="statistic",
                    checkable=True
                ),
                Claim(
                    original_text="Sensex dropped 3 percent in February.",
                    normalized_text="Sensex dropped 3 percent in February.",
                    start_seconds=20.0,
                    end_seconds=25.0,
                    domain="finance",
                    claim_type="statistic",
                    checkable=True
                )
            ])

    claims = extract_claims(segments, MockProvider())
    assert len(claims) == 2
    texts = [c.normalized_text for c in claims]
    assert "Nifty 50 fell 5 percent in January." in texts
    assert "Sensex dropped 3 percent in February." in texts


# =========================================================================
# 7. Pipeline Explicit Error When No Claims Extracted
# =========================================================================

@pytest.mark.anyio
async def test_pipeline_reports_explicit_error_when_no_claims(monkeypatch):
    monkeypatch.setattr("app.db.save_claim", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.db.save_audit", lambda *args, **kwargs: None)

    mock_serp = Mock()
    mock_serp.search.return_value = {"title": "Conversational Video", "published_date": "May 17, 2026"}
    mock_serp.cached_search.return_value = {
        "transcript": [
            {"start_ms": 0, "end_ms": 2000, "snippet": "Hello friends, welcome back."},
            {"start_ms": 2000, "end_ms": 4000, "snippet": "Like and subscribe to our channel."}
        ]
    }

    pipe = AuditPipeline(serp=mock_serp, provider=None)
    score = await pipe.run("audit-empty-claims-test", "https://www.youtube.com/watch?v=abcdefghijk")

    assert score.status == AuditStatus.COMPLETE
    assert len(score.claims) == 0
    assert score.error is not None
    assert "No defensible" in score.error


# =========================================================================
# 8. Regression Test for Multilingual Video (fK8rHVayHL4) Fallback Extraction
# =========================================================================

def test_hindi_multilingual_video_fallback_extraction_on_quota_error():
    """Verify that fallback extraction on Hindi/Hinglish transcripts extracts substantive financial claims when Gemini is unavailable or quota is exhausted."""
    segments = [
        TranscriptSegment(index=0, start_seconds=9.9, end_seconds=13.9, text_original="हे एवरीवन वेलकम बैक टू मनी मैटर शुभम दिस साइट सेबी रजिस्टर रिसर्च एनालिस।"),
        TranscriptSegment(index=1, start_seconds=13.9, end_seconds=18.6, text_original="देखिए बात कर लेते हैं निफ्टी के ऊपर निफ्टी का ये गैप जो है वो फिल होने आ चुका है।"),
        TranscriptSegment(index=2, start_seconds=144.2, end_seconds=148.8, text_original="दिस इज़ मिड कैप 100। सो यू कैन सी लाल ही लाल है मिड कैप में।"),
        TranscriptSegment(index=3, start_seconds=415.3, end_seconds=421.6, text_original="संभावना है तब तक एक सेलिंग प्रेशर रहेगा 24,400 से 24,600 के बीच में जब भी निफ्टी अटेम्प्ट करेगा।"),
        TranscriptSegment(index=4, start_seconds=536.6, end_seconds=544.6, text_original="ये 200 वीक का मूविंग एवरेज है निफ्टी 50 का।")
    ]

    class QuotaExhaustedProvider:
        def structured(self, operation, prompt, schema):
            raise LLMError("429 RESOURCE_EXHAUSTED: quota exceeded")

    claims = extract_claims(segments, QuotaExhaustedProvider())
    assert len(claims) >= 1
    assert any(c.domain == "finance" for c in claims)
    assert all(c.normalization_status == "validated" for c in claims)
    assert all(c.start_seconds >= 0 for c in claims)
    assert all(len(c.source_segment_indices) > 0 for c in claims)


# =========================================================================
# 9. Quality Filters: Greeting, Promo, Banter, and Fragment Exclusions
# =========================================================================

def test_filler_greetings_and_promo_exclusion():
    """Verify that greetings, channel promos, contact info, and conversational banter are rejected."""
    bad_segments = [
        TranscriptSegment(index=0, start_seconds=0.0, end_seconds=3.0, text_original="हे एवरीवन वेलकम बैक टू मनी मैटर शुभम दिस साइट सेबी रजिस्टर रिसर्च एनालिस।"),
        TranscriptSegment(index=1, start_seconds=3.0, end_seconds=6.0, text_original="हमारी सेबी रजिस्टर्ड सर्विज के लिए आप इस नंबर पे संपर्क करिए।"),
        TranscriptSegment(index=2, start_seconds=6.0, end_seconds=9.0, text_original="Telegram पे अगर आप कनेक्टेड नहीं है तो कनेक्ट हो जाइए।"),
        TranscriptSegment(index=3, start_seconds=9.0, end_seconds=12.0, text_original="तब तक निफ्टी क्या करता रहेगा? टाइम पास टाइम पास टुक टुक खेलता रहेगा। ओके?"),
        TranscriptSegment(index=4, start_seconds=12.0, end_seconds=15.0, text_original="क्लियर हुआ है निफ्टी के डायरेक्शन के लिए कैसे देखा जाएगा एज अ"),
    ]
    claims = extract_claims(bad_segments, provider=None)
    assert len(claims) == 0


def test_merging_adjacent_segments_into_complete_proposition():
    """Verify that adjacent segments forming one continuous sentence are merged cleanly."""
    split_segments = [
        TranscriptSegment(index=10, start_seconds=20.0, end_seconds=22.5, text_original="डबल टॉप फॉर्मेशन जिसमें कि ये लेवल टूटा"),
        TranscriptSegment(index=11, start_seconds=22.5, end_seconds=25.0, text_original="है और उसके बाद एक गैप फिलिंग का जो काम"),
        TranscriptSegment(index=12, start_seconds=25.0, end_seconds=28.0, text_original="है वो चालू हो गया है निफ्टी 50 में।")
    ]
    claims = extract_claims(split_segments, provider=None)
    assert len(claims) == 1
    assert claims[0].start_seconds == 20.0
    assert claims[0].end_seconds == 28.0
    assert claims[0].source_segment_indices == [10, 11, 12]
    assert "डबल टॉप फॉर्मेशन" in claims[0].original_text
    assert "चालू हो गया है" in claims[0].original_text


def test_serpapi_client_dynamic_env_key_loading(monkeypatch):
    """Verify that SerpApiClient dynamically resolves SERPAPI_API_KEY from the environment."""
    from app.serp import SerpApiClient
    monkeypatch.setenv("SERPAPI_API_KEY", "test_mock_key_12345")
    client = SerpApiClient()
    assert client.api_key == "test_mock_key_12345"

