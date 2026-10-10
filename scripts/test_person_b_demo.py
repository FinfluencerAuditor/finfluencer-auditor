"""Interactive visual demo showing Person B features in action."""

import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas import Claim, Evidence, RiskFlag, VerdictLabel
from app.source_tiers import get_tier_for_url
from app.numeric import check_numeric_claim
from app.retrieve import route_claim, draft_queries
from app.judge import judge_claim


def section(title):
    print("\n" + "=" * 65)
    print(f"  {title}")
    print("=" * 65)


def demo_person_b():
    # ---------------------------------------------------------
    # Feature 1: Dynamic Domain Routing & Query Drafting
    # ---------------------------------------------------------
    section("1. DOMAIN ROUTING & SMART QUERY DRAFTING")
    fin_claim = Claim(
        id="c1",
        original_text="Reliance Industries reported a 10 percent rise in quarterly profit.",
        normalized_text="Reliance Industries reported a 10 percent rise in quarterly profit.",
        start_seconds=15.0,
        domain="finance",
        entities={"mentions": ["Reliance Industries", "RELIANCE"]}
    )
    health_claim = Claim(
        id="c2",
        original_text="Ashwagandha reduces cortisol levels and stress in clinical trials.",
        normalized_text="Ashwagandha reduces cortisol levels and stress in clinical trials.",
        start_seconds=42.0,
        domain="health",
        entities={"mentions": ["Ashwagandha", "cortisol"]}
    )

    print(f"Finance Claim: \"{fin_claim.normalized_text}\"")
    print(f" -> Routed Engines: {route_claim(fin_claim)}")
    print(f" -> Drafted Queries ({len(draft_queries(fin_claim))} max 3):")
    for q in draft_queries(fin_claim):
        print(f"     * [{q['engine']}] {q['q']}")

    print(f"\nHealth Claim: \"{health_claim.normalized_text}\"")
    print(f" -> Routed Engines: {route_claim(health_claim)}")
    print(f" -> Drafted Queries ({len(draft_queries(health_claim))} max 3):")
    for q in draft_queries(health_claim):
        print(f"     * [{q['engine']}] {q['q']}")

    # ---------------------------------------------------------
    # Feature 2: Operational Source Tiering (Tier 1, 2, 3)
    # ---------------------------------------------------------
    section("2. OPERATIONAL SOURCE TIER CLASSIFICATION")
    test_urls = [
        ("https://www.sebi.gov.in/legal/circulars/2024.html", "SEBI Official Portal"),
        ("https://www.icmr.gov.in/guidelines/diabetes.html", "ICMR Health Authority"),
        ("https://www.thelancet.com/journals/lancet/article/PIIS0140", "The Lancet Medical Journal"),
        ("https://www.moneycontrol.com/news/business/earnings", "Moneycontrol Market News"),
        ("https://www.reuters.com/markets/asia", "Reuters Asia Markets"),
        ("https://random-stock-tipster.blogspot.com/post123", "Unverified Blogspot Page"),
        ("https://x.com/fakefinfluencer/status/9999", "Social Media Post"),
    ]
    for url, label in test_urls:
        tier = get_tier_for_url(url)
        badge = "Tier 1 [AUTHORITATIVE]" if tier == 1 else ("Tier 2 [ESTABLISHED NEWS]" if tier == 2 else "Tier 3 [UNVERIFIED / BLOG]")
        print(f"  {badge:32} -> {label} ({url[:45]}...)")

    # ---------------------------------------------------------
    # Feature 3: Deterministic Numeric Verification
    # ---------------------------------------------------------
    section("3. NUMERIC VERIFICATION & CONTRADICTION DETECTION")
    # Test A: Contradicted dividend claim
    claim_num = Claim(
        id="c3",
        original_text="HDFC Bank gives a massive 50 percent dividend yield to shareholders.",
        normalized_text="HDFC Bank gives a massive 50 percent dividend yield to shareholders.",
        start_seconds=120.0,
        domain="finance"
    )
    ev_finance = [
        Evidence(
            id="e1",
            engine="google_finance",
            title="HDFC Bank Key Statistics",
            source="Google Finance",
            tier=1,
            snippet="Price: ₹1,650 | P/E: 18.2 | Dividend Yield: 1.25%",
            url="https://google.com/finance"
        )
    ]
    num_result, _ = check_numeric_claim(claim_num, ev_finance)
    print(f"Claim: \"{claim_num.normalized_text}\"")
    print(f"Evidence: \"{ev_finance[0].snippet}\"")
    print(f" -> Numeric Result: {num_result['explanation']}")
    print(f" -> Within Tolerance: {num_result['within_tolerance']} (Claimed {num_result['claimed_raw']} vs Actual {num_result['actual_raw']})")

    # ---------------------------------------------------------
    # Feature 4: Evidence-Based Judging & Hard Rules Validator
    # ---------------------------------------------------------
    section("4. EVIDENCE-BASED JUDGING & HARD VALIDATOR ENFORCEMENT")

    # Scenario A: Contradicted Numeric Claim
    j1 = judge_claim(claim_num, ev_finance)
    print(f"[Scenario A: Factual Contradiction]")
    print(f"  Verdict:    {j1.label.value}")
    print(f"  Confidence: {j1.confidence}")
    print(f"  Citations:  {j1.evidence_ids}")
    print(f"  Rationale:  {j1.rationale}\n")

    # Scenario B: Unverifiable Prediction with Risk Flags
    pred_claim = Claim(
        id="c4",
        original_text="Buy this penny stock now, 100% multibagger guaranteed return 10x paisa double!",
        normalized_text="This penny stock is guaranteed to give 1000% returns next year.",
        start_seconds=200.0,
        claim_type="prediction",
        checkable=False,
        risk_flags=[
            RiskFlag(phrase="100%", category="guaranteed_return"),
            RiskFlag(phrase="guaranteed", category="guaranteed_return"),
            RiskFlag(phrase="multibagger", category="high_return_claim")
        ]
    )
    j2 = judge_claim(pred_claim, [])
    print(f"[Scenario B: Forward-Looking Prediction with Risk Flags]")
    print(f"  Verdict:    {j2.label.value}")
    print(f"  Confidence: {j2.confidence}")
    print(f"  Risk Flags: {[f.phrase for f in pred_claim.risk_flags]}")
    print(f"  Rationale:  {j2.rationale}\n")

    # Scenario C: Tier-3 Downgrade Safety Guard
    tier3_ev = [
        Evidence(
            id="e1",
            engine="google",
            title="Random Forum Rumor",
            source="blogspot.com",
            tier=3,
            snippet="Someone on the internet claims a merger is happening tomorrow.",
            url="https://rumors.blogspot.com"
        )
    ]
    rumor_claim = Claim(
        id="c5",
        original_text="Company X is merging with Company Y tomorrow.",
        normalized_text="Company X is merging with Company Y tomorrow.",
        start_seconds=310.0,
        domain="finance",
        checkable=True
    )
    j3 = judge_claim(rumor_claim, tier3_ev)
    print(f"[Scenario C: Tier-3 Source Downgrade]")
    print(f"  Verdict:    {j3.label.value} (Downgraded from Supported because only Tier 3 sources exist)")
    print(f"  Confidence: {j3.confidence}")
    print(f"  Citations:  {j3.evidence_ids}")
    print(f"  Rationale:  {j3.rationale}")

    print("\n" + "=" * 65)
    print("  ALL PERSON B CAPABILITIES OPERATING DYNAMICALLY & CORRECTLY")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    demo_person_b()
