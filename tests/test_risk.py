import pytest
from app.judge import judge_claim
from app.schemas import Claim, Evidence, RiskFlag, VerdictLabel


def test_risk_flag_preserves_factual_support():
    # A claim might contain a strong assertion or risk flag phrase, but if supported by authoritative evidence, verdict remains Supported
    claim = Claim(
        id="c1",
        original_text="This index return is guaranteed by government sovereign backing.",
        normalized_text="This bond return is backed by sovereign government guarantee.",
        start_seconds=0.0,
        domain="finance",
        claim_type="verifiable_fact",
        checkable=True,
        risk_flags=[RiskFlag(phrase="guaranteed", category="guaranteed_return")]
    )
    evidence = [
        Evidence(
            id="e1",
            engine="google",
            title="RBI Sovereign Gold Bonds FAQ",
            source="rbi.org.in",
            tier=1,
            snippet="Government of India guarantees the interest and redemption of Sovereign Gold Bonds.",
            url="https://rbi.org.in/sgb"
        )
    ]
    j = judge_claim(claim, evidence)
    assert j.label == VerdictLabel.SUPPORTED
    assert len(claim.risk_flags) == 1
    assert claim.risk_flags[0].phrase == "guaranteed"


def test_prediction_with_risk_flags():
    claim = Claim(
        id="c2",
        original_text="Buy this penny stock, 100% multibagger guaranteed return 10x paisa double!",
        normalized_text="This penny stock is guaranteed to double your money with 100% return.",
        start_seconds=0.0,
        domain="finance",
        claim_type="prediction",
        checkable=False,
        risk_flags=[
            RiskFlag(phrase="100%", category="guaranteed_return"),
            RiskFlag(phrase="guaranteed", category="guaranteed_return"),
            RiskFlag(phrase="multibagger", category="high_return_claim")
        ]
    )
    j = judge_claim(claim, [])
    assert j.label == VerdictLabel.UNVERIFIABLE
    assert len(claim.risk_flags) == 3
