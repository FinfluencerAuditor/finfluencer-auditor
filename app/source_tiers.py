"""Source tier classification for evidence ranking and verdict validation."""

import os
from pathlib import Path
from urllib.parse import urlparse
import yaml

_DEFAULT_TIER_1 = {
    "sebi.gov.in", "rbi.org.in", "nseindia.com", "bseindia.com", "amfiindia.com", "mca.gov.in",
    "incometaxindia.gov.in", "finmin.nic.in", "pib.gov.in", "india.gov.in", "gov.in", "nic.in",
    "mohfw.gov.in", "icmr.gov.in", "fssai.gov.in", "aiims.edu", "ayush.gov.in",
    "who.int", "nih.gov", "cdc.gov", "fda.gov", "sec.gov", "bis.org", "imf.org", "worldbank.org",
    "nature.com", "thelancet.com", "bmj.com", "jamanetwork.com", "nejm.org",
    "sciencedirect.com", "springer.com", "wiley.com", "cell.com", "ncbi.nlm.nih.gov",
    "pubmed.ncbi.nlm.nih.gov", "cochranelibrary.com", "frontiersin.org", "biorxiv.org",
    "medrxiv.org", "oup.com", "tandfonline.com", "plos.org", "pnas.org", "acpjournals.org",
    # Established museums, universities, archives, and historical collections.
    "si.edu", "smithsonianmag.com", "metmuseum.org", "rijksmuseum.nl", "britishmuseum.org",
    "loc.gov", "nationalarchives.gov.uk", "archives.gov", "history.org", "jstor.org",
    "harvard.edu", "yale.edu", "ox.ac.uk", "cam.ac.uk", "uchicago.edu", "stanford.edu",
    "amsterdam.nl", "huygens.knaw.nl", "dbnl.org", "eh.net", "nber.org",
    # Central banks and official financial/history records.
    "bankofengland.co.uk", "ecb.europa.eu", "federalreserve.gov", "bis.org", "fred.stlouisfed.org",
    "federalreservehistory.org", "history.state.gov",
}

_DEFAULT_TIER_2 = {
    "moneycontrol.com", "economictimes.indiatimes.com", "livemint.com", "business-standard.com",
    "financialexpress.com", "thehindubusinessline.com", "bloomberg.com", "reuters.com",
    "cnbctv18.com", "ndtvprofit.com", "wsj.com", "ft.com", "forbes.com", "cnbc.com",
    "marketwatch.com", "investopedia.com", "zeebiz.com", "fortune.com", "barrons.com", "morningstar.com",
    "thehindu.com", "indianexpress.com", "ndtv.com", "bbc.com", "bbc.co.uk",
    "timesofindia.indiatimes.com", "hindustantimes.com", "thewire.in", "scroll.in",
    "aljazeera.com", "theguardian.com", "apnews.com", "washingtonpost.com", "nytimes.com",
    "mayoclinic.org", "clevelandclinic.org", "hopkinsmedicine.org", "webmd.com",
    "healthline.com", "medicalnewstoday.com", "health.harvard.edu", "nhs.uk"
}

_DEFAULT_TIER_3 = {
    "youtube.com", "youtu.be", "twitter.com", "x.com", "reddit.com", "quora.com",
    "medium.com", "substack.com", "blogspot.com", "wordpress.com", "tumblr.com",
    "facebook.com", "instagram.com", "linkedin.com", "tiktok.com"
}


def _load_tiers_from_yaml() -> tuple[set[str], set[str], set[str]]:
    config_path = Path(__file__).resolve().parent.parent / "config" / "source_tiers.yaml"
    if not config_path.exists():
        return set(_DEFAULT_TIER_1), set(_DEFAULT_TIER_2), set(_DEFAULT_TIER_3)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            t1 = set(data.get("tier_1_domains", [])) or set(_DEFAULT_TIER_1)
            t2 = set(data.get("tier_2_domains", [])) or set(_DEFAULT_TIER_2)
            t3 = set(data.get("tier_3_domains", [])) or set(_DEFAULT_TIER_3)
            return t1, t2, t3
    except Exception:
        return set(_DEFAULT_TIER_1), set(_DEFAULT_TIER_2), set(_DEFAULT_TIER_3)


TIER_1_DOMAINS, TIER_2_DOMAINS, TIER_3_DOMAINS = _load_tiers_from_yaml()


def extract_domain(url_or_domain: str) -> str:
    """Normalize a URL or domain string to a clean lowercase hostname."""
    if not url_or_domain:
        return ""
    val = url_or_domain.strip().lower()
    if not (val.startswith("http://") or val.startswith("https://")):
        val = "https://" + val
    try:
        parsed = urlparse(val)
        host = parsed.netloc or parsed.path
        if ":" in host:
            host = host.split(":", 1)[0]
        if host.startswith("www."):
            host = host[4:]
        return host.strip("/").lower()
    except Exception:
        return url_or_domain.strip().lower()


def _domain_matches(host: str, domain_set: set[str]) -> bool:
    if not host:
        return False
    if host in domain_set:
        return True
    for d in domain_set:
        if d and (host.endswith("." + d) or host == d):
            return True
    # Check general government / educational TLDs for Tier 1
    if domain_set is TIER_1_DOMAINS:
        if host.endswith(".gov") or host.endswith(".gov.in") or host.endswith(".nic.in") or host.endswith(".mil"):
            return True
        if host.endswith(".edu") or host.endswith(".ac.in"):
            return True
    return False


def get_tier_for_url(url: str, source_name: str = "") -> int:
    """Classify a URL and/or source name into Tier 1, 2, or 3."""
    host = extract_domain(url)
    source_clean = source_name.lower().strip() if source_name else ""

    # Check Tier 1
    if _domain_matches(host, TIER_1_DOMAINS):
        return 1
    if any(auth in source_clean for auth in [
        "sebi", "rbi", "reserve bank", "sec.gov", "who", "icmr", "nih", "cdc", "fda",
        "lancet", "nature", "bmj", "nejm", "fssai", "mohfw", "pubmed", "google finance", "google scholar"
    ]):
        return 1

    # Check Tier 2
    if _domain_matches(host, TIER_2_DOMAINS):
        return 2
    if any(outlet in source_clean for outlet in [
        "reuters", "bloomberg", "moneycontrol", "economic times", "livemint", "mint",
        "financial express", "business standard", "hindu business line", "wsj", "wall street journal",
        "financial times", "cnbc", "ndtv profit", "the hindu", "indian express", "bbc",
        "times of india", "hindustan times", "mayo clinic", "webmd", "healthline", "harvard"
    ]):
        return 2

    # Check Tier 3
    if _domain_matches(host, TIER_3_DOMAINS):
        return 3

    # Default unclassified sources
    return 3
