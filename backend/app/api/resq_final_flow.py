"""ResQ V23 call coordinator: route matching, arrival time, app handoff, hangup consent."""
from __future__ import annotations
import re
import unicodedata
from app.api import v18_logic


def language(text, hint=None):
    if any('\u0c00' <= c <= '\u0c7f' for c in text): return 'te'
    if any('\u0900' <= c <= '\u097f' for c in text): return 'hi'
    return hint if hint in ('hi', 'te', 'en') else 'en'

def _norm(s):
    return re.sub(r'[^a-z0-9]+', '', unicodedata.normalize('NFKD', s).casefold())

def _roman(s):
    try:
        from unidecode import unidecode
        return _norm(unidecode(s))
    except ImportError:
        return _norm(s)

def _phonetic(s):
    s = _roman(s).replace('aa','a').replace('ee','i').replace('oo','u')
    s = re.sub(r'(.)\1+', r'\1', s)
    return re.sub(r'[aeiou]', '', s)

def _matches(text, pending):
    from difflib import SequenceMatcher
    try:
        from unidecode import unidecode
        spoken = unidecode(text).lower()
    except ImportError:
        spoken = text.lower()
    words = re.findall(r'[a-z]+', spoken)
    windows = [''.join(words[i:j]) for i in range(len(words))
               for j in range(i+1, min(len(words), i+4)+1)
               if len(_phonetic(''.join(words[i:j]))) >= 5]
    grouped = {}
    for parcel in pending:
        locality = str(parcel.get('locality') or '').strip()
        if locality: grouped.setdefault(locality, []).append(parcel)
    ranked = []
    for locality, parcels in grouped.items():
        key = _phonetic(locality)
        if len(key) < 5: continue
        variants = {key}
        if key.startswith('g'): variants.add('k'+key[1:])
        if key.startswith('k'): variants.add('g'+key[1:])
        score = max((SequenceMatcher(None, variant, _phonetic(part)).ratio()
                     for variant in variants for part in windows), default=0)
        if score >= .87: ranked.append((score, locality, parcels))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked or (len(ranked)>1 and ranked[0][0]-ranked[1][0]<.08): return []
    return ranked[0][2]

def _say(lang, hi, en, te):
    return {'hi':hi, 'en':en, 'te':te}.get(lang, hi)

def _consent(text):
    """Recognize an explicit hangup instruction in Hindi, Hinglish, English or Telugu."""
    s = unicodedata.normalize('NFKC', str(text or '')).casefold().strip()
    if not s: return False
    veto = ('नहीं','नही','मत ','रुको','रुकिए','अभी नहीं','not yet','do not','don\'t','dont',
            'wait','hold on','later','వద్దు','కాదు','ఆగ')
    if any(x in s for x in veto): return False
    commands = ('समाप्त कर','कॉल काट','कॉल कट','फोन काट','कॉल बंद','फोन बंद',
                'call समाप्त','call काट','call बंद','call cut','cut the call',
                'end the call','end call','hang up','disconnect','call end',
                'ముగించ','కాల్ కట్','ఫోన్ పెట్ట')
    if any(x in s for x in commands): return True
    yes = ('जी हाँ','जी हां','जी हा','हाँ','हां','बिल्कुल','ठीक है','yes','yeah',
           'sure','okay','ok','अवును','అవును','సరే')
    if any(re.fullmatch(re.escape(y)+r'[.!।, ]*', s) for y in yes): return True
    return bool(v18_logic.consent_yes(s))

def _eta(text):
    return v18_logic.extract_eta(text)

def process(actor, text, facts, incident, pending, hint=None):
    facts = dict(facts or {})
    lang = language(text, hint)
    stage = facts.get('_v22_stage', 'collecting')
    if stage == 'completed':
        return dict(facts=facts, reply='', end_call=True, complete=True,
                    stage='completed', language=lang)
    # Consent is handled FIRST, before other NLP which may overwrite the stage.
    if stage == 'consent' and _consent(text):
        facts['_v18_end_permission'] = True
        facts['_v22_stage'] = 'completed'
        return dict(facts=facts,
                    reply=_say(lang, f'धन्यवाद {actor} जी। आपकी अनुमति से कॉल समाप्त कर रही हूँ।',
                               f'Thank you, {actor}. Ending the call now.',
                               f'ధన్యవాదాలు {actor} గారు. కాల్ ముగిస్తున్నాను.'),
                    end_call=True, complete=True, stage='completed', language=lang)
    willing = v18_logic.willingness(text, None)
    if willing is not None and stage != 'consent': facts['accepted'] = willing
    if facts.get('accepted') is False:
        return dict(facts=facts, reply=_say(lang, f'{actor} जी, धन्यवाद। नमस्कार।',
                    f'Thank you, {actor}. Goodbye.', f'{actor} గారు, ధన్యవాదాలు.'),
                    end_call=True, complete=False, stage='declined', language=lang)
    if stage != 'consent':
        matched = _matches(text, pending)
        if matched:
            facts['route_candidate_ids'] = [str(p['id']) for p in matched]
            facts['route_localities'] = list(dict.fromkeys(str(p['locality']) for p in matched))
            facts['destination'] = ' · '.join(facts['route_localities'])
            facts['match_basis'] = 'manifest_locality_match_only'
        eta = _eta(text)
        if eta is not None: facts['eta_minutes'] = eta
    if facts.get('accepted') is not True:
        reply = _say(lang, f'{actor} जी, क्या आप राजू की डिलीवरी में मदद कर पाएंगे?',
                     f'{actor}, can you help with Raju’s deliveries?',
                     f'{actor} గారు, రాజు డెలివరీలకు సహాయం చేస్తారా?')
    elif not facts.get('route_localities'):
        reply = _say(lang, f'{actor} जी, आप किस रूट की तरफ जा रहे हैं?',
                     f'{actor}, which delivery area are you heading toward?',
                     f'{actor} గారు, మీరు ఏ ప్రాంతానికి వెళ్తున్నారు?')
    elif facts.get('eta_minutes') is None:
        count = len(facts['route_candidate_ids'])
        reply = _say(lang,
                     f'{actor} जी, आपके बताए क्षेत्र में {count} पेंडिंग पार्सल मिले हैं। ये अभी असाइन नहीं हुए हैं। राजू के पास कितने मिनट में पहुँचेंगे?',
                     f'{actor}, {count} pending parcel(s) match your area. How many minutes until you reach Raju?',
                     f'{actor} గారు, మీ ప్రాంతంలో {count} పెండింగ్ పార్సెల్‌లు ఉన్నాయి. రాజు దగ్గరకు ఎన్ని నిమిషాల్లో చేరుకుంటారు?')
    else:
        count, eta = len(facts['route_candidate_ids']), facts['eta_minutes']
        # A future-tense handoff is a promise, NOT proof of a successful app update.
        facts['driver_app_handoff_status'] = facts.get('driver_app_handoff_status', 'pending')
        reply = _say(lang,
                     f'{actor} जी, आपके बताए क्षेत्र से {count} पार्सल मैच हुआ है और {eta} मिनट का arrival time दर्ज है। राजू की लोकेशन और पार्सल की जानकारी आपके ड्राइवर ऐप पर भेज दी जाएगी। क्या मैं कॉल समाप्त कर सकती हूँ?' if count == 1 else
                     f'{actor} जी, आपके बताए क्षेत्र से {count} पार्सल मैच हुए हैं और {eta} मिनट का arrival time दर्ज है। राजू की लोकेशन और पार्सल की जानकारी आपके ड्राइवर ऐप पर भेज दी जाएगी। क्या मैं कॉल समाप्त कर सकती हूँ?',
                     f'{actor}, {count} parcels match your area and your arrival time is {eta} minutes. Raju’s location and parcel details will be sent to your driver app. May I end the call?',
                     f'{actor} గారు, మీ ప్రాంతానికి {count} పార్సెల్‌లు సరిపోలాయి. చేరుకునే సమయం {eta} నిమిషాలు. రాజు లొకేషన్, పార్సెల్ వివరాలు మీ డ్రైవర్ యాప్‌కు పంపబడతాయి. కాల్ ముగించవచ్చా?')
        facts['_v22_stage'] = 'consent'
        return dict(facts=facts, reply=reply, end_call=False, complete=False,
                    stage='consent', language=lang)
    facts['_v22_stage'] = 'collecting'
    return dict(facts=facts, reply=reply, end_call=False, complete=False,
                stage='collecting', language=lang)
