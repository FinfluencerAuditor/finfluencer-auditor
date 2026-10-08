import json
from pathlib import Path
from app.extract import ExtractedClaims, NormalizedClaims, NormalizedClaim, extract_claims
from app.ingest import normalize_transcript
from app.schemas import Claim

FIXTURES=Path(__file__).parents[1]/"fixtures"/"transcripts"

class FixtureProvider:
    def structured(self, operation, prompt, schema):
        transcript = prompt.split("TRANSCRIPT WINDOW:", 1)[-1]
        if "Nifty 50" in transcript or "निफ्टी 50" in transcript:
            return ExtractedClaims(claims=[Claim(original_text="निफ्टी 50 इस महीने 10 प्रतिशत गिरा है।",normalized_text="The Nifty 50 fell 10 percent this month.",start_seconds=0,end_seconds=2.2,domain="finance",claim_type="statistic",entities={"index":["Nifty 50"]},numeric_info=[{"original":"10 प्रतिशत","value":10,"unit":"percentage"},],checkable=True)])
        if "diabetes" in transcript.lower():
            return ExtractedClaims(claims=[Claim(original_text="यह supplement diabetes को cure नहीं करता है।",normalized_text="This supplement does not cure diabetes.",start_seconds=0,end_seconds=2.3,domain="health",claim_type="verifiable_fact",entities={"condition":["diabetes"]},checkable=True)])
        if "Market correction" in transcript:
            return ExtractedClaims(claims=[Claim(original_text="Market correction में portfolio 20% नीचे आया है।",normalized_text="The portfolio fell 20 percent during the market correction.",start_seconds=0,end_seconds=2.4,domain="finance",claim_type="statistic",entities={"instrument":["portfolio"]},numeric_info=[{"original":"20%","value":20,"unit":"percentage"}],checkable=True),Claim(original_text="This stock can double, लेकिन यह सिर्फ मेरा अनुमान है।",normalized_text="The speaker estimates that this stock could double.",start_seconds=2.4,end_seconds=5.3,domain="finance",claim_type="prediction",entities={"instrument":["stock"]},checkable=False)])
        if "should reduce" in transcript or "मत करना" in transcript:
            return ExtractedClaims(claims=[Claim(original_text="You should reduce your equity exposure.",normalized_text="The speaker advises reducing equity exposure.",start_seconds=2.2,end_seconds=5,domain="finance",claim_type="advice",checkable=False)])
        if "clinical trial" in transcript:
            return ExtractedClaims(claims=[Claim(original_text="A clinical trial found that the treatment reduced symptoms by 30%.",normalized_text="A clinical trial found that the treatment reduced symptoms by 30 percent.",start_seconds=0,end_seconds=2.6,domain="health",claim_type="statistic",checkable=True,numeric_info=[{"original":"30%","value":30,"unit":"percentage"}])])
        return ExtractedClaims()

def load(name):
    return normalize_transcript(json.loads((FIXTURES/name).read_text()))

def test_fixture_languages_preserve_original_timestamps():
    for name in ["english_finance.json","hindi_finance.json","hinglish_finance.json","english_health.json","hinglish_health.json","general.json"]:
        segments=load(name)
        assert segments and segments[0].text_original
        assert segments[0].start_seconds==0
        assert segments[0].end_seconds>0

def test_hindi_finance_is_normalized_and_classified():
    claims=extract_claims(load("hindi_finance.json"),FixtureProvider())
    assert claims[0].original_text.startswith("निफ्टी")
    assert claims[0].normalized_text.startswith("The Nifty 50")
    assert claims[0].domain=="finance" and claims[0].claim_type=="statistic"
    assert claims[0].numeric_info[0]["value"]==10

def test_hinglish_prediction_and_finance_domain():
    claims=extract_claims(load("hinglish_finance.json"),FixtureProvider())
    prediction=next(c for c in claims if c.claim_type=="prediction")
    assert prediction.domain=="finance" and prediction.checkable is False
    assert prediction.original_text.startswith("This stock")

def test_health_claim_and_advice_are_distinguished():
    claims=extract_claims(load("english_health.json"),FixtureProvider())
    assert claims[0].domain=="health" and claims[0].claim_type=="statistic"
    assert claims[0].numeric_info[0]["value"]==30

def test_fragment_rejection_and_timestamp_span():
    segments=normalize_transcript({"transcript":[{"start_ms":0,"end_ms":1000,"snippet":"The largest investors"},{"start_ms":1000,"end_ms":2400,"snippet":"saw portfolios fall 40-50% in 2026."}]})
    class Provider:
        def structured(self,*args):
            return ExtractedClaims(claims=[Claim(original_text="The largest investors saw portfolios fall 40-50% in 2026.",normalized_text="The largest investors saw portfolios fall 40-50% in 2026.",start_seconds=0,end_seconds=2.4,domain="finance",claim_type="statistic",checkable=True)])
    claims=extract_claims(segments,Provider())
    assert len(claims)==1
    assert claims[0].start_seconds==0 and claims[0].end_seconds==2.4
    assert claims[0].numeric_info[0]["value"]==[40,50]

def test_leading_and_trailing_transcript_repairs_are_rejected():
    segments=normalize_transcript({"transcript":[{"start_ms":0,"end_ms":1000,"snippet":"से। यह पिछले वाक्य का टुकड़ा"},{"start_ms":1000,"end_ms":2400,"snippet":"पोर्टफोलियो 40% नीचे है।"}]})
    claims=extract_claims(segments)
    assert all(not c.original_text.startswith("से।") for c in claims)

def test_claim_limit_and_deduplication():
    segments=normalize_transcript({"transcript":[{"start_ms":i*1000,"end_ms":(i+1)*1000,"snippet":f"The Nifty 50 fell {i+1} percent in 2026."} for i in range(12)]})
    class Provider:
        def structured(self,*args):
            return ExtractedClaims(claims=[Claim(original_text="The Nifty 50 fell 10 percent in 2026.",normalized_text="The Nifty 50 fell 10 percent in 2026.",start_seconds=0,end_seconds=1,domain="finance",claim_type="statistic",checkable=True)])
    claims=extract_claims(segments,Provider())
    assert len(claims)<=8

def test_invalid_hindi_normalization_is_not_silently_copied():
    segments=normalize_transcript({"transcript":[{"start_ms":0,"end_ms":2200,"snippet":"भारत में महंगाई पिछले साल काफी बढ़ी है।"}]})
    assert extract_claims(segments) == []

def test_invalid_normalization_gets_one_safe_retry():
    segments=normalize_transcript({"transcript":[{"start_ms":0,"end_ms":2200,"snippet":"निफ्टी 50 इस महीने 10 प्रतिशत गिरा है।"}]})
    class Provider:
        def structured(self, operation, prompt, schema):
            if operation=="extract_v2":
                return ExtractedClaims(claims=[Claim(original_text="निफ्टी 50 इस महीने 10 प्रतिशत गिरा है।",normalized_text="निफ्टी 50 इस महीने 10 प्रतिशत गिरा है।",start_seconds=0,end_seconds=2.2,domain="finance",claim_type="statistic",checkable=True)])
            assert operation=="normalize_v1"
            return NormalizedClaims(claims=[NormalizedClaim(index=0,normalized_text="The Nifty 50 fell 10 percent this month.",domain="finance",claim_type="statistic",entities={"index":["Nifty 50"]},checkable=True)])
    claims=extract_claims(segments,Provider())
    assert len(claims)==1
    assert claims[0].normalization_status=="validated"
    assert claims[0].normalized_text.startswith("The Nifty 50")

def test_obvious_transcript_tail_fragment_is_rejected():
    segments=normalize_transcript({"transcript":[{"start_ms":0,"end_ms":1000,"snippet":"The portfolio fell 20 percent but"}]})
    class Provider:
        def structured(self,*args):
            return ExtractedClaims(claims=[Claim(original_text="The portfolio fell 20 percent but",normalized_text="The portfolio fell 20 percent but",start_seconds=0,end_seconds=1,domain="finance",claim_type="statistic",checkable=True)])
    assert extract_claims(segments,Provider())==[]

def test_source_indices_are_merged_with_model_timestamp_span():
    segments=normalize_transcript({"transcript":[
        {"start_ms":0,"end_ms":1000,"snippet":"The Nifty 50"},
        {"start_ms":1000,"end_ms":2200,"snippet":"fell 10 percent this month."},
    ]})
    class Provider:
        def structured(self,*args):
            return ExtractedClaims(claims=[Claim(original_text="The Nifty 50 fell 10 percent this month.",normalized_text="The Nifty 50 fell 10 percent this month.",start_seconds=0,end_seconds=2.2,domain="finance",claim_type="statistic",source_segment_indices=[1],checkable=True)])
    claims=extract_claims(segments,Provider())
    assert claims[0].source_segment_indices==[0,1]
