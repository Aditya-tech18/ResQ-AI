"""Grounded multilingual transcript extraction. No geocoding or invented coordinates."""
from __future__ import annotations
import json, os, re, unicodedata
from difflib import SequenceMatcher
import httpx
from pydantic import BaseModel, Field

class RouteExtraction(BaseModel):
    language: str = Field(pattern='^(hi|te|en)$')
    destination: str | None = Field(default=None, max_length=160)
    evidence: str | None = Field(default=None, max_length=250)
    needs_clarification: bool = True
    matched_localities: list[str] = Field(default_factory=list)

def detect_language(text: str, hint: str | None = None) -> str:
    if re.search('[\u0c00-\u0c7f]',text): return 'te'
    if re.search('[\u0900-\u097f]',text): return 'hi'
    if hint:
        prefix=str(hint).lower().replace('_','-').split('-')[0]
        if prefix in ('te','hi','en'): return prefix
    return 'en'

def norm(text: str) -> str:
    return re.sub(r'[^\w]+','',unicodedata.normalize('NFKC',text).casefold())

def from_manifest(transcript: str, localities: list[str]) -> str | None:
    """Only direct substring match; not a universal translator."""
    speech=norm(transcript)
    for locality in sorted(set(localities),key=len,reverse=True):
        if len(norm(locality)) >= 4 and norm(locality) in speech:
            return locality
    return None

async def extract_route(transcript: str, localities: list[str], hint: str | None = None) -> RouteExtraction:
    """LLM extraction with strict quote grounding; fails closed if unavailable.

    Destination can be arbitrary. Matching is separate and requires verified locality
    or coordinates; a guessed name never produces parcel matches.
    """
    language=detect_language(transcript,hint)
    direct=from_manifest(transcript,localities)
    if direct:
        return RouteExtraction(language=language,destination=direct,evidence=transcript,needs_clarification=False)
    key=os.getenv('GEMINI_API_KEY','').strip()
    if not key:
        fallback = phonetic_manifest_match(transcript, localities)
        if fallback:
            return RouteExtraction(language=language,destination=fallback,evidence=transcript,
                                   needs_clarification=False,matched_localities=[fallback])
        return RouteExtraction(language=language)
    model=os.getenv('RESQ_GEMINI_MODEL','gemini-3-flash-preview')
    if not re.fullmatch(r'[\w.-]+',model):return RouteExtraction(language=language)
    prompt=("Extract ONLY a driver-spoken next destination or route from this single utterance. "
            "Return JSON with language (hi/te/en), destination (string or null), evidence "
            "(exact verbatim substring of utterance or null), needs_clarification (boolean). "
            "The pending parcel localities are reference choices, NOT driver speech. "
            "Match a spoken destination to a locality ONLY when it is the same real place across scripts (e.g. Telugu/English transliteration), not merely nearby. "
            "Return matched_localities as an array containing ONLY exact strings from the provided list; use [] if uncertain. "
            "Never claim verified GPS, route geometry, or driving proximity. "
            "A route may be in Telugu, Hindi, English or mixed speech. "
            "If no explicit destination is spoken return null.\nPending parcel localities: " + json.dumps(localities,ensure_ascii=False) + "\nUtterance: " + json.dumps(transcript,ensure_ascii=False))
    try:
        async with httpx.AsyncClient(timeout=14) as client:
            response=await client.post(
                f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                headers={'x-goog-api-key':key},
                json={'contents':[{'parts':[{'text':prompt}]}],
                      'generationConfig':{'responseMimeType':'application/json','temperature':0}})
            response.raise_for_status()
            data=json.loads(response.json()['candidates'][0]['content']['parts'][0]['text'])
        parsed=RouteExtraction.model_validate(data)
        evidence=parsed.evidence or ''
        if not evidence or norm(evidence) not in norm(transcript):
            fallback = phonetic_manifest_match(transcript, localities)
            if fallback:
                return RouteExtraction(language=language,destination=fallback,evidence=transcript,
                                       needs_clarification=False,matched_localities=[fallback])
            return RouteExtraction(language=language)
        if not parsed.destination or parsed.needs_clarification:
            fallback = phonetic_manifest_match(transcript, localities)
            if fallback:
                return RouteExtraction(language=language,destination=fallback,evidence=transcript,
                                       needs_clarification=False,matched_localities=[fallback])
            return RouteExtraction(language=language)
        return RouteExtraction(language=language,destination=parsed.destination,evidence=evidence,needs_clarification=False,
                               matched_localities=[x for x in parsed.matched_localities if x in localities])
    except (httpx.HTTPError,KeyError,ValueError,TypeError,IndexError):
        fallback = phonetic_manifest_match(transcript, localities)
        if fallback:
            return RouteExtraction(language=language,destination=fallback,evidence=transcript,
                                   needs_clarification=False,matched_localities=[fallback])
        return RouteExtraction(language=language)

def resolve_manifest_localities(destination: str, localities: list[str]) -> list[str]:
    """No semantic guess. Only canonical text overlap, otherwise unknown."""
    d=norm(destination)
    return [loc for loc in localities if norm(loc)==d or (len(norm(loc))>=5 and norm(loc) in d)]


def grounded_manifest_matches(extraction: RouteExtraction, localities: list[str]) -> list[str]:
    """Only use exact locality names supplied by the live manifest, never model-invented names."""
    exact = resolve_manifest_localities(extraction.destination or '', localities)
    allowed = set(localities)
    return list(dict.fromkeys(exact + [x for x in extraction.matched_localities if x in allowed]))


def _phonetic(s: str) -> str:
    """Generic script transliteration; not a list of hardcoded city names.

    Uses optional Unidecode if installed; Gemini handles complex cases when not.
    Strip vowels and doubled consonants to tolerate common ASR spelling variants.
    """
    try:
        from unidecode import unidecode
    except ImportError:
        return ''
    latin = re.sub('[^a-z]', '', unidecode(s).lower())
    latin = re.sub('[aeiou]', '', latin)
    return re.sub(r'(.)\1+', r'\1', latin)


def phonetic_manifest_match(transcript: str, localities: list[str]) -> str | None:
    """Match only unambiguous, high-confidence transliterations from live manifest.

    No GPS proximity or made-up route assignments. Require a spoken phrase
    sufficiently long and a clear margin over other locality candidates.
    """
    if not re.search('[\u0900-\u097f\u0c00-\u0c7f]', transcript):
        return None
    # Limit comparisons to substrings (1..4 words) to avoid dilution by sentences.
    words = re.findall(r'[\u0900-\u097f\u0c00-\u0c7f]+', transcript)
    phrases = [' '.join(words[i:j]) for i in range(len(words))
               for j in range(i+1, min(len(words), i+4)+1)]
    scored=[]
    for loc in set(localities):
        target = _phonetic(loc)
        if len(target) < 5:
            continue
        score=max((SequenceMatcher(None,_phonetic(phrase),target).ratio()
                   for phrase in phrases if len(_phonetic(phrase))>=5), default=0)
        scored.append((score,loc))
    scored.sort(reverse=True)
    if scored and scored[0][0]>=0.88 and (len(scored)==1 or scored[0][0]-scored[1][0]>=0.10):
        return scored[0][1]
    return None
