import pytest
from app.source_tiers import extract_domain, get_tier_for_url


def test_extract_domain():
    assert extract_domain("https://www.sebi.gov.in/enforcement/orders.html") == "sebi.gov.in"
    assert extract_domain("http://moneycontrol.com/news/business") == "moneycontrol.com"
    assert extract_domain("https://SUB.economictimes.indiatimes.com:443/markets") == "sub.economictimes.indiatimes.com"
    assert extract_domain("youtube.com/watch?v=123") == "youtube.com"
    assert extract_domain("") == ""


def test_tier_1_authorities_and_journals():
    # Indian regulators & government
    assert get_tier_for_url("https://www.sebi.gov.in/legal/circulars.html") == 1
    assert get_tier_for_url("https://rbi.org.in/scripts/BS_PressReleaseDisplay.aspx") == 1
    assert get_tier_for_url("https://www.nseindia.com/market-data") == 1
    assert get_tier_for_url("https://incometaxindia.gov.in/news") == 1
    assert get_tier_for_url("https://pib.gov.in/PressReleasePage.aspx") == 1

    # Indian & Global health bodies
    assert get_tier_for_url("https://www.icmr.gov.in/guidelines") == 1
    assert get_tier_for_url("https://mohfw.gov.in/advisories") == 1
    assert get_tier_for_url("https://www.who.int/news-room") == 1
    assert get_tier_for_url("https://www.cdc.gov/cancer") == 1
    assert get_tier_for_url("https://www.fda.gov/drugs") == 1

    # Peer-reviewed journals
    assert get_tier_for_url("https://www.nature.com/articles/s41586-024-001") == 1
    assert get_tier_for_url("https://www.thelancet.com/journals/lancet/article") == 1
    assert get_tier_for_url("https://www.bmj.com/content/380/bmj") == 1
    assert get_tier_for_url("https://pubmed.ncbi.nlm.nih.gov/38291029/") == 1
    assert get_tier_for_url("https://www.nejm.org/doi/full/10.1056") == 1

    # Historical institutions, universities, archives, and official financial history
    assert get_tier_for_url("https://www.rijksmuseum.nl/en/stories/tulip-mania") == 1
    assert get_tier_for_url("https://www.huygens.knaw.nl/en/resources") == 1
    assert get_tier_for_url("https://www.nber.org/papers/dot-com-bubble") == 1
    assert get_tier_for_url("https://www.federalreservehistory.org/essays") == 1


def test_tier_2_established_news():
    # Financial news
    assert get_tier_for_url("https://www.moneycontrol.com/news/business/markets") == 2
    assert get_tier_for_url("https://economictimes.indiatimes.com/markets/stocks") == 2
    assert get_tier_for_url("https://www.livemint.com/market/stock-market-news") == 2
    assert get_tier_for_url("https://www.reuters.com/markets/asia") == 2
    assert get_tier_for_url("https://www.bloomberg.com/news/articles") == 2
    assert get_tier_for_url("https://www.cnbctv18.com/market") == 2

    # Mainstream & medical news
    assert get_tier_for_url("https://www.thehindu.com/business") == 2
    assert get_tier_for_url("https://indianexpress.com/article/business") == 2
    assert get_tier_for_url("https://www.mayoclinic.org/diseases-conditions") == 2
    assert get_tier_for_url("https://www.webmd.com/diet/features") == 2


def test_tier_3_blogs_and_social():
    assert get_tier_for_url("https://www.youtube.com/watch?v=abc") == 3
    assert get_tier_for_url("https://x.com/finfluencer/status/123") == 3
    assert get_tier_for_url("https://reddit.com/r/IndianStockMarket") == 3
    assert get_tier_for_url("https://medium.com/@user/multibagger-tip") == 3
    assert get_tier_for_url("https://randomfinblog.xyz/penny-stocks") == 3
