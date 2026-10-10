from unittest.mock import Mock

from app.judge import judge_claim
from app.retrieve import draft_queries, parse_engine_response, retrieve_claim
from app.schemas import Claim, Evidence, VerdictLabel


def _index_fund_claim() -> Claim:
    return Claim(
        id="index-1",
        original_text="Index funds track the Sensex with low tracking error and low expenses.",
        normalized_text="Index funds track the Sensex with low tracking error and low expense ratio.",
        start_seconds=12,
        domain="finance",
        entities={
            "named_entities": ["Sensex"],
            "finance_terms": ["index funds", "tracking error", "expense ratio"],
        },
        checkable=True,
    )


def test_queries_preserve_specific_finance_assertion_and_official_context():
    queries = draft_queries(_index_fund_claim())
    query_text = " ".join(q["q"].lower() for q in queries)

    assert "sensex" in query_text
    assert "index" in query_text and "fund" in query_text
    assert "tracking" in query_text
    assert any("bseindia" in q["q"].lower() or "sebi" in q["q"].lower() or "amfi" in q["q"].lower() for q in queries)
    assert len(queries) <= 3


def test_topic_adjacent_market_story_is_not_index_fund_evidence():
    claim = _index_fund_claim()
    serp = Mock()
    serp.search.return_value = {
        "organic_results": [
            {
                "title": "Sensex rises as Indian markets gain",
                "link": "https://www.reuters.com/markets/india/sensex-rises",
                "source": "Reuters",
                "snippet": "The Sensex gained as broad market sentiment improved.",
            },
            {
                "title": "BSE Sensex index funds and tracking error explained",
                "link": "https://www.amfiindia.com/investor/index-funds",
                "source": "AMFI",
                "snippet": "Index funds track a benchmark such as the Sensex; tracking error and expense ratio affect replication.",
            },
        ]
    }

    evidence, status = retrieve_claim(claim, serp)

    assert status == "complete"
    assert len(evidence) == 1
    assert evidence[0].source == "AMFI"
    assert evidence[0].retrieved_at


def test_general_sensex_story_cannot_support_index_fund_claim():
    claim = _index_fund_claim()
    evidence = [
        Evidence(
            id="e1",
            engine="google_news",
            title="Sensex climbs on positive market sentiment",
            source="Reuters",
            tier=2,
            snippet="The Sensex rose as Indian equities moved higher.",
            url="https://www.reuters.com/markets/india/sensex",
        )
    ]

    judgment = judge_claim(claim, evidence)

    assert judgment.label == VerdictLabel.NO_EVIDENCE
    assert judgment.evidence_ids == []


def test_relevant_primary_evidence_can_support_specific_claim():
    claim = _index_fund_claim()
    evidence = [
        Evidence(
            id="e1",
            engine="google",
            title="SEBI guidance on index funds and benchmark tracking",
            source="SEBI",
            tier=1,
            snippet="SEBI confirms that an index fund seeks to replicate its benchmark, such as the Sensex; tracking error and expense ratio are relevant measures.",
            url="https://www.sebi.gov.in/index-funds",
        )
    ]

    judgment = judge_claim(claim, evidence)

    assert judgment.label == VerdictLabel.SUPPORTED
    assert judgment.evidence_ids == ["e1"]


def test_plain_factual_snippet_can_support_without_confirmation_word():
    claim = Claim(
        id="supply-demand",
        original_text="Stock prices are based on supply and demand.",
        normalized_text="Stock prices are determined by investor supply and demand.",
        start_seconds=0,
        domain="finance",
        entities={"named_entities": ["stock market"]},
        claim_type="verifiable_fact",
        checkable=True,
    )
    evidence = [
        Evidence(
            id="e1",
            engine="google_news",
            title="How supply and demand drive stock market changes",
            source="Investopedia",
            tier=2,
            snippet="Supply and demand dynamics play a crucial role in stock market price movements.",
            url="https://example.test/supply-demand",
        )
    ]

    judgment = judge_claim(claim, evidence)

    assert judgment.label == VerdictLabel.SUPPORTED
    assert judgment.evidence_ids == ["e1"]


def test_natural_language_entity_is_not_inferred_as_finance_ticker():
    claim = Claim(
        id="dot-com",
        original_text="The dot-com mania occurred in the 1990s.",
        normalized_text="The dot-com mania occurred in the 1990s.",
        start_seconds=0,
        domain="finance",
        entities={"mentions": ["dot-com mania"]},
        claim_type="historical_fact",
        checkable=True,
    )

    queries = draft_queries(claim)

    assert all(query["engine"] != "google_finance" for query in queries)
    assert all("DOT:NSE" not in query["q"] for query in queries)


def test_finance_mention_is_retained_during_judgment_validation():
    claim = Claim(
        id="tulip-history",
        original_text="A tulip bulb sold for more than ten times an annual craftsman's wage.",
        normalized_text="A tulip bulb sold for more than ten times an annual craftsman's wage.",
        start_seconds=0,
        domain="finance",
        entities={"mentions": ["tulip bulb", "craftsman"]},
        claim_type="historical_fact",
        checkable=True,
    )
    evidence = [
        Evidence(
            id="e1",
            engine="google",
            title="Tulip bulb prices in 1637",
            source="Historical reference",
            tier=3,
            snippet="A tulip bulb was traded at ten times the annual wage of a workman.",
            url="https://example.test/tulip-history",
        )
    ]

    judgment = judge_claim(claim, evidence)

    assert judgment.label == VerdictLabel.MIXED
    assert judgment.evidence_ids == ["e1"]


def test_historical_queries_add_domain_vocabulary():
    claim = Claim(
        id="history-vocab",
        original_text="A speculative bubble was followed by a crash; merchants used the harbor for trade; tulip petals showed colour breaking.",
        normalized_text="A speculative bubble was followed by a crash; merchants used the harbor for trade; tulip petals showed colour breaking.",
        start_seconds=0,
        domain="other",
        claim_type="historical_fact",
        checkable=True,
    )
    query_text = " ".join(q["q"].lower() for q in draft_queries(claim))

    assert "mania" in query_text and "overvaluation" in query_text
    assert "shipping" in query_text and "merchants" in query_text
    assert "color" in query_text and "petal" in query_text and "streaks" in query_text


def test_compound_events_are_searched_separately_and_partial_support_is_mixed():
    claim = Claim(
        id="compound-history",
        original_text="Tulip mania involved extreme speculation, the real estate crash followed overvaluation, and Pets.com collapsed during the dot-com bubble.",
        normalized_text="Tulip mania involved extreme speculation, the real estate crash followed overvaluation, and Pets.com collapsed during the dot-com bubble.",
        start_seconds=0,
        domain="finance",
        entities={"mentions": ["tulip mania", "real estate", "Pets.com", "dot-com bubble"]},
        claim_type="historical_fact",
        checkable=True,
    )
    serp = Mock()

    def search(_engine, q):
        q = q.lower()
        if "tulip" in q:
            return {"organic_results": [{
                "title": "Tulip mania speculation in the Dutch Golden Age",
                "link": "https://www.history.org/tulip-mania",
                "source": "History archive",
                "snippet": "Tulip mania involved extreme speculation and rapidly rising bulb prices.",
            }]}
        if "pets" in q:
            return {"organic_results": [{
                "title": "Pets.com collapsed during the dot-com bubble",
                "link": "https://www.reuters.com/pets-com-collapse",
                "source": "Reuters",
                "snippet": "Pets.com collapsed during the dot-com bubble after heavy losses.",
            }]}
        return {"organic_results": [{
            "title": "Unrelated property market commentary",
            "link": "https://example.test/property",
            "source": "Unrelated",
            "snippet": "Property prices were discussed without a historical crash or overvaluation.",
        }]}

    serp.search.side_effect = search
    evidence, status = retrieve_claim(claim, serp)
    judgment = judge_claim(claim, evidence)

    assert status == "complete"
    subclaims = {e.metadata.get("subclaim", "").lower() for e in evidence}
    assert any("tulip" in subclaim for subclaim in subclaims)
    assert any("pets.com" in subclaim for subclaim in subclaims)
    assert judgment.label == VerdictLabel.MIXED


def test_title_only_results_are_retryable_metadata_not_proof():
    items = parse_engine_response("google", {"organic_results": [{
        "title": "Tulip mania archive record",
        "link": "https://www.history.org/tulip-mania",
        "source": "History archive",
        "snippet": "",
    }]})

    assert items[0]["metadata"]["content_available"] is False
    assert items[0]["metadata"]["content_retryable"] is True
    assert items[0]["metadata"]["retry_candidate"]["url"] == "https://www.history.org/tulip-mania"

    title_only = Evidence(
        id="title-only",
        engine="google",
        title=items[0]["title"],
        source=items[0]["source"],
        tier=1,
        snippet="",
        url=items[0]["url"],
        metadata=items[0]["metadata"],
    )
    claim = Claim(
        id="title-only-claim",
        normalized_text="Tulip mania occurred in the 1630s.",
        start_seconds=0,
        domain="other",
        claim_type="historical_fact",
        checkable=True,
    )
    assert judge_claim(claim, [title_only]).label == VerdictLabel.NO_EVIDENCE


def test_compound_claim_with_only_one_supported_event_is_mixed_with_clear_rationale():
    claim = Claim(
        id="one-event-supported",
        normalized_text="Tulips, real estate, and Pets.com were overvalued before their prices collapsed.",
        original_text="Tulips, real estate, and Pets.com were overvalued before their prices collapsed.",
        start_seconds=0,
        domain="finance",
        entities={"mentions": ["tulips", "real estate", "Pets.com"]},
        claim_type="historical_fact",
        checkable=True,
    )
    serp = Mock()

    def search(_engine, q, **_kwargs):
        q = q.lower()
        if "tulip" in q:
            return {"organic_results": [{
                "title": "Tulip mania prices and collapse in the Dutch Republic",
                "link": "https://www.history.org/tulip-mania",
                "source": "Historical archive",
                "snippet": "Historical records describe tulip mania prices and the later collapse of the market.",
            }]}
        if "real estate" in q:
            return {"organic_results": [{
                "title": "10 Best Real Estate Stocks To Buy Now",
                "link": "https://finance.yahoo.com/news/10-best-real-estate-stocks-153451445.html",
                "source": "Yahoo Finance",
                "snippet": "Current real estate stocks and REITs for investors.",
            }]}
        return {"organic_results": [{
            "title": "Pets.com products and online shopping",
            "link": "https://example.test/pets",
            "source": "Unrelated",
            "snippet": "Pets.com sold pet supplies online.",
        }]}

    serp.search.side_effect = search
    evidence, _ = retrieve_claim(claim, serp)
    judgment = judge_claim(claim, evidence)

    assert [e.metadata["subclaim_role"] for e in evidence] == ["tulip-price event"]
    assert judgment.label == VerdictLabel.MIXED
    assert "tulip-price event" in judgment.rationale
    assert "real-estate event" in judgment.rationale
    assert "pets.com event" in judgment.rationale


def test_current_real_estate_stock_results_are_rejected_for_historical_crash_event():
    claim = Claim(
        id="real-estate-crash",
        normalized_text="The historical real estate bubble ended in a major price crash.",
        start_seconds=0,
        domain="finance",
        entities={"mentions": ["real estate"]},
        claim_type="historical_fact",
        checkable=True,
    )
    serp = Mock()
    serp.search.return_value = {"organic_results": [{
        "title": "Real Estate Stocks",
        "link": "https://www.morningstar.com/best-investments/real-estate-stocks",
        "source": "Morningstar",
        "snippet": "Real estate stocks include mortgage companies, property managers, and REITs.",
    }]}

    evidence, _ = retrieve_claim(claim, serp)

    assert evidence == []


def test_tulip_virus_mechanism_is_separate_from_historical_chronology():
    claim = Claim(
        id="virus-chronology",
        normalized_text="During the 1630s, an outbreak of tulip breaking virus produced streaks on tulip petals.",
        start_seconds=0,
        domain="other",
        entities={"mentions": ["tulip breaking virus"]},
        claim_type="historical_fact",
        checkable=True,
    )
    serp = Mock()

    def search(_engine, q, **_kwargs):
        q = q.lower()
        if "biological" in q or "mechanism" in q:
            return {"organic_results": [{
                "title": "Tulip breaking virus disrupts petal pigmentation",
                "link": "https://www.ncbi.nlm.nih.gov/pmc/articles/example",
                "source": "National Institutes of Health",
                "snippet": "Tulip breaking virus disrupts pigmentation and produces streaked or broken tulip petals.",
            }]}
        return {"organic_results": []}

    serp.search.side_effect = search
    evidence, _ = retrieve_claim(claim, serp)
    judgment = judge_claim(claim, evidence)

    assert any(e.metadata.get("subclaim_role") == "biological_mechanism" for e in evidence)
    assert judgment.label == VerdictLabel.MIXED
    assert "biological_mechanism" in judgment.rationale
    assert "historical_appearance" in judgment.rationale or "scientific_chronology" in judgment.rationale


def test_historical_queries_target_reputable_dot_com_and_amsterdam_sources():
    dot_com = Claim(
        id="dot-com-history",
        normalized_text="The dot-com mania occurred in the 1990s.",
        start_seconds=0,
        domain="other",
        claim_type="historical_fact",
        checkable=True,
    )
    amsterdam = Claim(
        id="amsterdam-history",
        normalized_text="Amsterdam was an important port and commercial center by the 1630s.",
        start_seconds=0,
        domain="other",
        claim_type="historical_fact",
        checkable=True,
    )

    dot_queries = draft_queries(dot_com)
    amsterdam_queries = draft_queries(amsterdam)

    assert any("nber.org" in q["q"] or "federalreservehistory.org" in q["q"] for q in dot_queries)
    assert any("amsterdam.nl" in q["q"] or "huygens.knaw.nl" in q["q"] for q in amsterdam_queries)


def test_tier3_downgrade_rationale_matches_mixed_verdict():
    claim = Claim(
        id="golden-age-rationale",
        normalized_text="The Netherlands entered the Dutch Golden Age during the 17th century.",
        start_seconds=0,
        domain="other",
        claim_type="historical_fact",
        entities={"mentions": ["Netherlands", "Dutch Golden Age"]},
        checkable=True,
    )
    evidence = [Evidence(
        id="e1",
        engine="google",
        title="The Dutch Golden Age in the 17th century",
        source="Unverified history blog",
        tier=3,
        snippet="The Dutch Golden Age refers to the Netherlands during much of the 17th century.",
        url="https://example.test/dutch-golden-age",
    )]

    judgment = judge_claim(claim, evidence)

    assert judgment.label == VerdictLabel.MIXED
    assert "Tier-3" in judgment.rationale
    assert "fully supported" in judgment.rationale
