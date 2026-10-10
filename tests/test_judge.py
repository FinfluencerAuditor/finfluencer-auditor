import pytest
from app.judge import LLMVerdictSchema, judge_claim, validate_judgment
from app.schemas import Claim, Evidence, Judgment, VerdictLabel


def test_judge_uncheckable_and_predictions():
    # Prediction
    pred_claim = Claim(
        id="c1",
        original_text="This stock will 10x by 2026 guaranteed.",
        start_seconds=0.0,
        claim_type="prediction",
        checkable=False
    )
    j = judge_claim(pred_claim, [])
    assert j.label == VerdictLabel.UNVERIFIABLE
    assert j.confidence == "High"
    assert j.evidence_ids == []

    # Opinion
    opinion_claim = Claim(
        id="c2",
        original_text="I believe this is the best company in the world.",
        start_seconds=0.0,
        claim_type="opinion",
        checkable=False
    )
    j = judge_claim(opinion_claim, [])
    assert j.label == VerdictLabel.UNVERIFIABLE


def test_judge_no_evidence_when_empty():
    claim = Claim(
        id="c3",
        original_text="Obscure startup raised 100 crore in stealth.",
        normalized_text="Obscure startup raised 100 crore in stealth.",
        start_seconds=0.0,
        domain="finance",
        checkable=True
    )
    j = judge_claim(claim, [])
    assert j.label == VerdictLabel.NO_EVIDENCE
    assert j.confidence == "Low"
    assert j.evidence_ids == []


def test_judge_supported_with_tier_1_evidence():
    claim = Claim(
        id="c4",
        original_text="RBI holds repo rate steady at 6.5%.",
        normalized_text="RBI holds repo rate steady at 6.5%.",
        start_seconds=0.0,
        domain="finance",
        checkable=True
    )
    evidence = [
        Evidence(
            id="e1",
            engine="google",
            title="Monetary Policy Statement",
            source="rbi.org.in",
            tier=1,
            snippet="The Monetary Policy Committee decided to keep the policy repo rate unchanged at 6.50%.",
            url="https://rbi.org.in/mpc"
        )
    ]
    j = judge_claim(claim, evidence)
    assert j.label == VerdictLabel.SUPPORTED
    assert "e1" in j.evidence_ids
    assert j.confidence in {"Medium", "High"}


def test_judgment_identifies_deterministic_fallback_and_provider_mode():
    claim = Claim(
        id="mode-1", original_text="RBI holds repo rate steady at 6.5%.",
        normalized_text="RBI holds repo rate steady at 6.5%.", start_seconds=0.0,
        domain="finance", checkable=True,
    )
    evidence = [Evidence(
        id="e1", engine="google", title="Monetary Policy Statement", source="rbi.org.in",
        tier=1, snippet="The repo rate remains 6.50%.", url="https://rbi.org.in/mpc",
    )]

    class Provider:
        def structured(self, _operation, _prompt, _schema):
            return LLMVerdictSchema(label="Supported", confidence="High", rationale="The source states the rate.", evidence_ids=["e1"])

    assert judge_claim(claim, evidence).analysis_mode == "deterministic_fallback"
    assert judge_claim(claim, evidence, Provider()).analysis_mode == "gemini"


def test_provider_failure_is_explicit_and_does_not_invent_a_verdict():
    claim = Claim(
        id="provider-failure", original_text="Acme revenue increased 12% in 2024.",
        normalized_text="Acme revenue increased 12% in 2024.", start_seconds=0.0,
        domain="finance", checkable=True,
    )
    evidence = [Evidence(
        id="e1", engine="google_news", title="Acme revenue increased 12%",
        source="News", tier=2, snippet="Acme revenue increased 12% in 2024.",
        url="https://news.example/acme", date="2024-12-31",
    )]

    class ExhaustedProvider:
        def structured(self, *_args, **_kwargs):
            raise RuntimeError("provider unavailable")

    judgment = judge_claim(claim, evidence, ExhaustedProvider())
    assert judgment.analysis_mode == "deterministic_fallback"
    assert judgment.label == VerdictLabel.SUPPORTED
    assert judgment.evidence_ids == ["e1"]


def test_validator_drops_hallucinated_evidence_ids():
    claim = Claim(id="c5", original_text="Claim text", start_seconds=0.0, checkable=True)
    real_evidence = [
        Evidence(
            id="e1",
            engine="google",
            title="Real Title",
            source="reuters.com",
            tier=2,
            snippet="Real snippet",
            url="https://reuters.com"
        )
    ]
    # Simulated model hallucinating an ID 'e99'
    fake_judgment = Judgment(
        claim_id="c5",
        label=VerdictLabel.SUPPORTED,
        confidence="High",
        rationale="Source e99 proves this claim.",
        evidence_ids=["e99"]
    )
    validated = validate_judgment(fake_judgment, real_evidence, claim)
    # e99 must be dropped
    assert "e99" not in validated.evidence_ids
    # Because no valid citations remain, Supported must be reset to No evidence
    assert validated.label == VerdictLabel.NO_EVIDENCE
    assert validated.confidence == "Low"


def test_validator_downgrades_tier_3_only_verdicts():
    claim = Claim(id="c6", original_text="Claim text", start_seconds=0.0, checkable=True)
    tier_3_evidence = [
        Evidence(
            id="e1",
            engine="google",
            title="Random blog post",
            source="blogspot.com",
            tier=3,
            snippet="Someone on blog claims this happened.",
            url="https://random.blogspot.com/post"
        )
    ]
    judgment = Judgment(
        claim_id="c6",
        label=VerdictLabel.SUPPORTED,
        confidence="High",
        rationale="A blog confirms this.",
        evidence_ids=["e1"]
    )
    validated = validate_judgment(judgment, tier_3_evidence, claim)
    # Cannot be Supported with only Tier 3 citations -> must downgrade to Mixed
    assert validated.label == VerdictLabel.MIXED
    assert validated.confidence == "Low"
    assert "Tier-3" in validated.rationale or "unverified" in validated.rationale


def test_neutral_rationale_scrubbing():
    claim = Claim(id="c7", original_text="Claim text", start_seconds=0.0, checkable=True)
    judgment = Judgment(
        claim_id="c7",
        label=VerdictLabel.NO_EVIDENCE,
        confidence="Low",
        rationale="This influencer is a scammer and cannot be trusted. Sentence two. Sentence three. Sentence four should be truncated.",
        evidence_ids=[]
    )
    validated = validate_judgment(judgment, [], claim)
    # Ad-hominem wording must be cleaned
    assert "scammer" not in validated.rationale.lower()
    # Sentence count must be <= 3
    sentences = validated.rationale.split(". ")
    assert len(sentences) <= 3
