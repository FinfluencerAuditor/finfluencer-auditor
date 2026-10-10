import pytest
from app.numeric import extract_numeric_items, values_match, check_numeric_claim
from app.schemas import Claim, Evidence


def test_extract_numeric_items():
    text = "Nifty 50 crashed 10.5% while Reliance traded at ₹2,500 with a P/E of 24.8 and market cap 18.5 lakh crore."
    items = extract_numeric_items(text)
    types = {i["type"] for i in items}

    assert "percentage" in types
    assert "pe_ratio" in types
    assert "currency" in types or "denominated_value" in types

    pct_item = next(i for i in items if i["type"] == "percentage")
    assert pct_item["value"] == 10.5

    pe_item = next(i for i in items if i["type"] == "pe_ratio")
    assert pe_item["value"] == 24.8


def test_values_match_tolerance():
    # Exact match
    match, diff = values_match(10.0, 10.0, "percentage")
    assert match is True and diff == 0.0

    # Within percentage tolerance (e.g. 10.0 vs 10.4)
    match, diff = values_match(10.0, 10.4, "percentage")
    assert match is True

    # Outside tolerance (e.g. 10.0 vs 18.0)
    match, diff = values_match(10.0, 18.0, "percentage")
    assert match is False

    # Large denominated values (e.g. 5 lakh crore = 5e12 vs 5.1e12)
    match, diff = values_match(5e12, 5.1e12, "denominated_value")
    assert match is True

    # 100% vs 10%
    match, diff = values_match(100.0, 10.0, "percentage")
    assert match is False


def test_check_numeric_claim_supported():
    claim = Claim(
        id="c1",
        original_text="The benchmark Nifty fell 10 percent this quarter.",
        normalized_text="The benchmark Nifty fell 10 percent this quarter.",
        start_seconds=0,
        domain="finance"
    )
    evidence = [
        Evidence(
            id="e1",
            engine="google_news",
            title="Markets: Nifty dropped 10.2% in broad-based selloff",
            source="reuters.com",
            tier=2,
            snippet="The Nifty index fell 10.2 percent amid relentless foreign outflows.",
            url="https://reuters.com/markets"
        )
    ]
    res, state = check_numeric_claim(claim, evidence)
    assert state == "complete"
    assert res is not None
    assert res["within_tolerance"] is True
    assert res["source_evidence_id"] == "e1"


def test_check_numeric_claim_contradicted():
    claim = Claim(
        id="c2",
        original_text="HDFC Bank gives a 50 percent dividend yield.",
        normalized_text="HDFC Bank gives a 50 percent dividend yield.",
        start_seconds=0,
        domain="finance"
    )
    evidence = [
        Evidence(
            id="e1",
            engine="google_finance",
            title="HDFC Bank Stock Quote",
            source="Google Finance",
            tier=1,
            snippet="Dividend yield: 1.4% | P/E: 19.5",
            url="https://google.com/finance"
        )
    ]
    res, state = check_numeric_claim(claim, evidence)
    assert state == "complete"
    assert res is not None
    assert res["within_tolerance"] is False
    assert "contradicts" in res["explanation"]


def test_check_numeric_claim_no_numbers():
    claim = Claim(
        id="c3",
        original_text="SEBI issues new guidelines for registered investment advisors.",
        normalized_text="SEBI issues new guidelines for registered investment advisors.",
        start_seconds=0,
        domain="finance"
    )
    evidence = [
        Evidence(
            id="e1",
            engine="google",
            title="SEBI RIA Consultation Paper",
            source="sebi.gov.in",
            tier=1,
            snippet="SEBI released new framework for advisors.",
            url="https://sebi.gov.in"
        )
    ]
    res, state = check_numeric_claim(claim, evidence)
    assert res is None
    assert state == "no_numeric_data"
