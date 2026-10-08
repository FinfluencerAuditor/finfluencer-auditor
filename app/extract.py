import hashlib
import re
from difflib import SequenceMatcher
from pydantic import BaseModel, Field
from .schemas import Claim, RiskFlag, TranscriptSegment
from .llm import LLMError, LLMProvider

class ExtractedClaims(BaseModel):
    claims: list[Claim] = Field(default_factory=list)

class NormalizedClaim(BaseModel):
    index: int
    normalized_text: str
    domain: str = "other"
    claim_type: str = "other"
    entities: dict = {}
    checkable: bool = True

class NormalizedClaims(BaseModel):
    claims: list[NormalizedClaim] = Field(default_factory=list)

_FRAGMENT_ENDINGS = re.compile(r"(?:\b(?:of|the|and|or|to|for|with|in|on|from|that|which|because|as|so|not)\s*|(?:का|के|की|में|से|को|और|या|कि|पर|तक|लिए|तो|नहीं|पे|चीज)\s*)$", re.I)
_FRAGMENT_STARTINGS = re.compile(r"^\s*(?:plus|and|so|because|from|not|then|also|प्लस|और|तो|क्योंकि|से|हुई|नहीं|लीजिए|दूंगा)(?:\s|[।,.!?]|$)", re.I)
_OBVIOUS_FRAGMENT_ENDINGS = re.compile(r"(?:\b(?:and|or|but|because|if|then|you|the|of|to|for|with|that|which)\s*|(?:और|या|लेकिन|क्योंकि|अगर|तो|आप|की|कि)\s*)$", re.I)
_RISK_PATTERNS = (
    ("guaranteed_return", re.compile(r"\b(?:guaranteed|guarantee|risk[- ]?free|sure[- ]?shot)\b", re.I)),
    ("high_return_claim", re.compile(r"\b(?:double your money|multibagger|10x|100% return)\b", re.I)),
    ("buy_sell_recommendation", re.compile(r"\b(?:buy|sell|accumulate|exit|target price)\b", re.I)),
    ("medical_advice", re.compile(r"\b(?:you should take|stop taking|dosage|prescription)\b", re.I)),
    ("disease_treatment_claim", re.compile(r"\b(?:cure|treats|heals|prevents)\b", re.I)),
    ("future_prediction", re.compile(r"\b(?:will|going to|expects?|forecast|projected|target)\b", re.I)),
    ("specific_price_target", re.compile(r"\b(?:target|reach)\s*(?:₹|rs\.?|inr)?\s*[\d,]+", re.I)),
    ("leverage_or_debt", re.compile(r"\b(?:leverage|borrow|debt|loan|margin)\b", re.I)),
    ("urgency", re.compile(r"\b(?:today|now|before Monday|last chance|act fast)\b", re.I)),
    ("fear_or_panic", re.compile(r"\b(?:crash|panic|collapse|disaster| डर|घबराहट|गिरावट)\b", re.I)),
    ("supplement_claim", re.compile(r"\b(?:supplement|vitamin|herbal|ashwagandha)\b", re.I)),
)
_DOMAIN_TERMS = {
    "finance": re.compile(r"\b(?:stock|share|equity|equities|bond|mutual fund|portfolio|market|nifty|sensex|index|inflation|interest rate|rbi|fii|fpi|commodity|crypto|bitcoin|return|yield|invest|goldman sachs)\b|(?:शेयर|स्टॉक|इक्विटी|बॉन्ड|म्यूचुअल फंड|पोर्टफोलियो|बाजार|महंगाई|ब्याज|निफ्टी|सेंसेक्स|निवेश|रिटर्न|एफआईआई|इंडेक्स|स्माल कैप|कैप|मार्केट|पीई|ईयर|बॉन्ड ईल्ड)", re.I),
    "health": re.compile(r"\b(?:disease|symptom|medicine|treatment|nutrition|health|supplement|vitamin|clinical|drug|doctor|cure|cancer|diabetes)\b|(?:बीमारी|लक्षण|दवा|इलाज|पोषण|स्वास्थ्य|विटामिन|क्लिनिकल|डॉक्टर)", re.I),
}
_TYPE_WORDS = {
    "prediction": re.compile(r"\b(?:will|going to|expects?|forecast|projected|may|could|target)\b", re.I),
    "advice": re.compile(r"\b(?:should|must|avoid|consider|recommend|buy|sell|take|reduce|increase)\b", re.I),
    "opinion": re.compile(r"\b(?:i think|i believe|in my view|seems|feel that|लगता है|मेरे हिसाब से)\b", re.I),
    "statistic": re.compile(r"(?:\d+(?:\.\d+)?\s*%|₹|\b(?:in|during)\s+20\d{2}\b)", re.I),
}
_NON_CLAIM_FILLER = re.compile(r"(?:like and subscribe|फटाफट लाइक|चाय की चुस्की|सिंपलीसिटी पे बिलीव|वीडियो आप लोगों के लिए ही है)", re.I)

def chunk_transcript(segments: list[TranscriptSegment], window=150, overlap=20):
    if not segments: return []
    out=[]; start=0.0; end=segments[-1].end_seconds
    while start<=end:
        items=[s for s in segments if s.end_seconds>start and s.start_seconds<start+window]
        if items: out.append(items)
        if start+window>=end: break
        start += window-overlap
    return out

def _prompt(items):
    text="\n".join(f"SEGMENT {s.index if s.index is not None else i} [{s.start_seconds:.1f}-{s.end_seconds:.1f}]: {s.text_original}" for i,s in enumerate(items))
    return f'''You are extracting claims from a YouTube transcript. The input may be English, Hindi, Hinglish, or mixed Hindi-English.

Return JSON only in this shape: {{"claims": [{{...}}]}}.
Extract complete, independently understandable propositions, not arbitrary transcript lines or sentence fragments. Merge adjacent transcript segments when they form one claim. Ignore greetings, filler, ads, conversational repairs, and rhetorical questions unless they contain a substantive proposition. Extract only what the speaker actually states or clearly implies; never add world knowledge or missing context.

For every claim return original_text (exact source-language wording), normalized_text (a concise, grammatical English sentence; translate Hindi/Hinglish into English faithfully rather than copying Devanagari), start_seconds, end_seconds, source_segment_indices, domain (finance|health|other), claim_type (verifiable_fact|prediction|opinion|advice|historical_fact|statistic|comparison|other), entities, numeric_info (original expression/value/range/unit/context), risk_flags (only defensible categories), and checkable. Predictions, opinions, advice, testimonials, and ambiguous claims are not checkable.

CRITICAL NORMALIZATION RULE: when original_text contains Hindi/Devanagari, normalized_text MUST be English-only (except proper names or symbols). Never copy the Hindi sentence into normalized_text. If you cannot translate it faithfully, omit the claim. Each retained claim must stand alone as a complete proposition with a subject and a predicate.

Do not output a fragment ending in an unfinished connector or a transcript repair. If a proposition is incomplete in this window, omit it rather than guessing. Do not invent context, facts, entities, numbers, or translations. Preserve Hindi and code-switching in original_text. Preserve negation and contrast exactly: words such as "नहीं" mean "not", and "not X, but Y" must never be normalized as "X and Y". Ignore filler and do not turn predictions or recommendations into facts. Do not attach a claim to names or numbers from a different transcript segment unless those words are included in original_text.

Example: original_text="निफ्टी 50 इस महीने 10% गिरा है"; normalized_text="The Nifty 50 fell 10% this month"; domain="finance"; claim_type="statistic"; checkable=true.
Example: original_text="I think the market will recover"; normalized_text="The speaker thinks the market will recover"; domain="finance"; claim_type="opinion"; checkable=false.

TRANSCRIPT WINDOW:
{text}'''

def _numeric_info(text):
    found=[]
    for pattern,unit in [(r"₹\s?[\d,]+(?:\.\d+)?(?:\s*(?:lakh|crore|million|billion))?","currency"),(r"\b\d+(?:\.\d+)?\s*(?:-|to|–|—)\s*\d+(?:\.\d+)?\s*%","percentage_range"),(r"\b\d+(?:\.\d+)?\s*%","percentage"),(r"\b20\d{2}\b","year")]:
        for match in re.finditer(pattern,text,re.I):
            original=match.group(0); numbers=[float(x.replace(",","")) for x in re.findall(r"\d+(?:\.\d+)?",original)]
            if any(item["start"] <= match.start() and item["end"] >= match.end() for item in found):
                continue
            found.append({"original":original,"value":numbers if len(numbers)>1 else (numbers[0] if numbers else original),"unit":unit,"context":text[max(0,match.start()-45):match.end()+45],"start":match.start(),"end":match.end()})
    for item in found:
        item.pop("start",None); item.pop("end",None)
    return found

def _entity_mentions(text):
    entities={}
    for label, terms in {
        "finance_terms": r"Nifty(?:\s*50)?|Sensex|RBI|FII|FPI|Bitcoin|Indian equities|mutual funds?|portfolio|bond yields?|market correction|Goldman Sachs|निफ्टी|सेंसेक्स|आरबीआई|एफआईआई|इक्विटी|पोर्टफोलियो|बॉन्ड|बाजार|निवेश|रिटर्न",
        "health_terms": r"diabetes|cancer|vitamin|supplement|medicine|treatment|clinical trial|RBI",
    }.items():
        hits=[]
        for match in re.finditer(terms,text,re.I):
            value=match.group(0)
            if value not in hits: hits.append(value)
        if hits: entities[label]=hits
    # Preserve clearly named Latin entities without pretending generic words are names.
    proper=[m.group(0) for m in re.finditer(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b",text) if m.group(0) not in {"The Speaker"}]
    if proper: entities["named_entities"]=sorted(set(proper))
    return entities

def _domain(text,proposed="other"):
    if proposed in {"finance","health"}: return proposed
    for domain,pattern in _DOMAIN_TERMS.items():
        if pattern.search(text): return domain
    return "other"

def _claim_type(text,proposed="other"):
    allowed={"verifiable_fact","prediction","opinion","advice","historical_fact","statistic","comparison","other"}
    if proposed in allowed and proposed!="other": return proposed
    if _TYPE_WORDS["opinion"].search(text): return "opinion"
    if _TYPE_WORDS["advice"].search(text): return "advice"
    if _TYPE_WORDS["prediction"].search(text): return "prediction"
    if _TYPE_WORDS["statistic"].search(text): return "statistic"
    return "verifiable_fact"

def _risk_flags(text,existing):
    flags={flag.category:flag for flag in existing if flag.category}
    for category,pattern in _RISK_PATTERNS:
        match=pattern.search(text)
        if match and category not in flags: flags[category]=RiskFlag(phrase=match.group(0),category=category)
    return list(flags.values())

def _is_meaningful(claim):
    original=claim.original_text.strip()
    text=(claim.normalized_text or original).strip()
    same_as_original=claim.normalized_text.strip()==claim.original_text.strip()
    complete_boundary=bool(re.search(r"[.!?।]$",text)) or bool(re.search(r"(?:%|₹|\d)$",text))
    return len(text)>=15 and len(text.split())>=3 and not _NON_CLAIM_FILLER.search(text) and not _FRAGMENT_STARTINGS.search(original) and not _OBVIOUS_FRAGMENT_ENDINGS.search(original) and not (_FRAGMENT_ENDINGS.search(text) and same_as_original) and not (same_as_original and not complete_boundary)

def _needs_english_normalization(claim):
    original=claim.original_text or claim.quote_original
    normalized=claim.normalized_text or claim.claim_english
    if not re.search(r"[\u0900-\u097F]", original):
        return False
    if not normalized or normalized.strip()==original.strip():
        return True
    letters=len(re.findall(r"[A-Za-z\u0900-\u097F]", normalized))
    devanagari=len(re.findall(r"[\u0900-\u097F]", normalized))
    return bool(letters and devanagari / letters > .20)

def _normalization_prompt(claims):
    candidates="\n".join(f"CANDIDATE {i}: {claim.original_text}" for i,claim in enumerate(claims))
    return f'''Return JSON only: {{"claims":[{{"index":0,"normalized_text":"English sentence","domain":"finance|health|other","claim_type":"verifiable_fact|historical_fact|statistic|prediction|opinion|advice|comparison|other","entities":{{}},"checkable":true}}]}}.
Translate only candidates that are complete propositions. Preserve uncertainty and attribution: "could" is not "will", and "I think" or advice must remain attributed to the speaker. Do not add any facts, numbers, entities, causes, or context. normalized_text must be grammatical English; do not copy Devanagari. Omit a candidate if it is a fragment or cannot be translated faithfully.

{candidates}'''

def _fallback(items):
    if not items: return ExtractedClaims()
    groups=[]; current=[]
    for segment in items:
        current.append(segment)
        if re.search(r"[.!?।]$",segment.text_original) or len(current)>=3:
            groups.append(current);current=[]
    if current: groups.append(current)
    claims=[]
    for group in groups:
        original=" ".join(s.text_original for s in group).strip()
        if not original: continue
        claim=Claim(original_text=original,normalized_text=original,start_seconds=group[0].start_seconds,end_seconds=group[-1].end_seconds,source_segment_indices=[s.index for s in group if s.index is not None],context=original)
        claim.domain=_domain(original);claim.claim_type=_claim_type(original);claim.checkable=claim.claim_type in {"verifiable_fact","historical_fact","statistic","comparison"};claim.numeric_info=_numeric_info(original);claim.risk_flags=_risk_flags(original,[]);claims.append(claim)
    return ExtractedClaims(claims=claims)

def _align_claim(claim,items):
    claim.original_text=claim.original_text or claim.quote_original;claim.normalized_text=claim.normalized_text or claim.claim_english or claim.original_text;claim.quote_original=claim.original_text;claim.claim_english=claim.normalized_text
    if claim.end_seconds is None or claim.end_seconds<claim.start_seconds: claim.end_seconds=claim.start_seconds
    overlaps=[s for s in items if s.end_seconds>=claim.start_seconds and s.start_seconds<=claim.end_seconds]
    if overlaps:
        claim.start_seconds=min(claim.start_seconds,overlaps[0].start_seconds);claim.end_seconds=max(claim.end_seconds,overlaps[-1].end_seconds)
        claim.source_segment_indices=sorted(set(claim.source_segment_indices+[s.index for s in overlaps if s.index is not None]))
    source=f"{claim.original_text} {claim.normalized_text}";claim.domain=_domain(source,claim.domain);claim.claim_type=_claim_type(source,claim.claim_type)
    if claim.claim_type in {"prediction","opinion","advice","other"}: claim.checkable=False
    detected_numeric=_numeric_info(claim.original_text)
    claim.numeric_info=detected_numeric or claim.numeric_info
    claim.risk_flags=_risk_flags(source,claim.risk_flags)
    detected_entities=_entity_mentions(source)
    for key,value in detected_entities.items():
        if not claim.entities.get(key): claim.entities[key]=value
    claim.normalization_status="needs_review" if _needs_english_normalization(claim) else "validated"
    return claim

def _retry_invalid_normalization(claims, provider):
    invalid=[claim for claim in claims if _needs_english_normalization(claim)]
    if not invalid or provider is None:
        return claims
    try:
        response=provider.structured("normalize_v1",_normalization_prompt(invalid),NormalizedClaims)
    except LLMError:
        return claims
    by_index={item.index:item for item in response.claims}
    for index,claim in enumerate(invalid):
        item=by_index.get(index)
        if not item or _needs_english_normalization(Claim(original_text=claim.original_text,normalized_text=item.normalized_text,start_seconds=0)):
            continue
        claim.normalized_text=item.normalized_text;claim.claim_english=item.normalized_text
        if item.domain in {"finance","health","other"}: claim.domain=item.domain
        if item.claim_type: claim.claim_type=item.claim_type
        if item.entities: claim.entities.update(item.entities)
        claim.checkable=item.checkable;claim.normalization_status="validated"
    return claims

def extract_claims(segments,provider: LLMProvider|None=None):
    all_claims=[]
    for items in chunk_transcript(segments):
        try: result=provider.structured("extract_v2",_prompt(items),ExtractedClaims) if provider else _fallback(items)
        except LLMError: result=_fallback(items)
        aligned=[_align_claim(claim,items) for claim in result.claims]
        all_claims.extend(_retry_invalid_normalization(aligned,provider))
    unique=[]
    for claim in all_claims:
        if claim.normalization_status != "validated":
            continue
        if not _is_meaningful(claim): continue
        key=re.sub(r"\W+"," ",claim.normalized_text.lower()).strip()
        if not key: continue
        existing=next((x for x in unique if x.domain==claim.domain and SequenceMatcher(None,key,re.sub(r"\W+"," ",x.normalized_text.lower()).strip()).ratio()>=.90),None)
        if existing:
            existing.start_seconds=min(existing.start_seconds,claim.start_seconds);existing.end_seconds=max(existing.end_seconds or 0,claim.end_seconds or 0);existing.source_segment_indices=sorted(set(existing.source_segment_indices+claim.source_segment_indices));continue
        claim.id="clm_"+hashlib.sha1(f"{key}:{claim.start_seconds}".encode()).hexdigest()[:12];claim.priority=(5 if claim.checkable else 1)+(3 if claim.domain in {"finance","health"} else 0)+min(len(claim.numeric_info),2)+min(len(claim.risk_flags),2)+min(len(key.split())/100,.5);unique.append(claim)
    unique.sort(key=lambda claim:(claim.checkable,claim.priority),reverse=True)
    return unique[:8]
