"""ResQ V18 deterministic turn controller and SQLite live-report writer.
Only local simulated calls. No GPS, real dialing, assignment or notifications are implied.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from app.api import v14_nearby
from app.api import live_report


def start_report(call_id, actor, incident):
    if actor == 'Raju':
        return
    location = incident.get('location') or 'Location not provided'
    live_report.start_report(live_report.StartReport(
        call_id=str(call_id), rescue_driver=actor,
        breakdown_driver=incident.get('driver') or 'Raju',
        breakdown_location=location,
    ))


def save(call_id, actor, inc, facts, stage, *, ended=False):
    if actor == 'Raju':
        return
    start_report(call_id, actor, inc)
    route = facts.get('route_localities') or []
    ids = facts.get('route_candidate_ids')
    payload = {'call_status': 'completed' if ended else (
        'awaiting_eta' if stage == 'eta' else
        'awaiting_permission' if stage == 'consent' else 'in_progress')}
    if route:
        payload['next_route'] = ' · '.join(route)
    elif facts.get('destination'):
        payload['next_route'] = facts['destination']
    if isinstance(ids, list):
        payload['parcel_ids'] = ids
    if facts.get('eta_minutes') is not None:
        payload['pickup_eta_minutes'] = facts['eta_minutes']
    if facts.get('current_location'):
        payload['current_location'] = facts['current_location']
    if facts.get('_v18_end_permission') is True:
        payload['end_permission'] = True
    live_report.update_report(str(call_id), live_report.UpdateReport(**payload))


def extract_eta(text):
    """Conservative ETA parsing; do not infer minutes from a street or parcel number."""
    s = text.casefold().translate(str.maketrans('०१२३४५६७८९', '0123456789'))
    s = s.translate(str.maketrans('౦౧౨౩౪౫౬౭౮౯', '0123456789'))
    m = re.search(r'(?<!\w)(\d{1,3})\s*(?:minutes?|mins?|मिनट|నిమిష(?:ాలు|లు)?)(?!\w)', s)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 240 else None
    # Whole-word matches avoid extracting 'one' from 'someone'.
    words = {'एक':1,'दो':2,'तीन':3,'चार':4,'पांच':5,'पाँच':5,'छह':6,'सात':7,'आठ':8,'नौ':9,'दस':10,'पंद्रह':15,'बीस':20,
             'ఒక':1,'రెండు':2,'మూడు':3,'నాలుగు':4,'ఐదు':5,'ఆరు':6,'ఏడు':7,'ఎనిమిది':8,'తొమ్మిది':9,'పది':10,
             'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,'fifteen':15,'twenty':20}
    if re.search(r'minute|min\b|मिनट|నిమిష', s):
        for word,n in sorted(words.items(),key=lambda item:-len(item[0])):
            if re.search(r'(?<!\w)'+re.escape(word)+r'(?!\w)',s):return n
    return None


def consent_yes(text):
    """Only explicit permission; ambiguous acknowledgement never ends a call."""
    s = re.sub(r'\s+', ' ', text.casefold().strip())
    # Any qualification or negation vetoes an otherwise positive utterance.
    veto = ('नहीं','नही','मत','रुको','रुकिए','लेकिन','पर रु','अभी नहीं',
            'wait','hold','but','not','no','stop','later','వద్దు','ఆగ','కాదు','కానీ')
    if any(w in s for w in veto): return False
    allowed = ('हाँ, कॉल समाप्त कर','हां कॉल समाप्त कर','कॉल समाप्त कर दीजिए',
               'कॉल काट दीजिए','काट दीजिए','जी हाँ, कॉल','हाँ समाप्त',
               'yes end the call','yes you may end','you may hang up',
               'please end the call','end the call','hang up now',
               'కాల్ ముగించండి','కాల్ కట్ చేయండి','అవును కాల్ ముగించండి')
    return any(w in s for w in allowed)


def reply_in_language(language, hi, en, te):
    return {'hi':hi,'en':en,'te':te}.get(language,hi)

def willingness(text, proposed):
    s=text.casefold()
    if any(w in s for w in ('नहीं','नही','मना','busy','cannot','can\'t','not possible','వద్దు')):return False
    if any(w in s for w in ('हाँ','हां','बिल्कुल','बिलकुल','कर सकता','कर सकती','yes','sure','अवును','అవును','సరే')):return True
    return proposed if type(proposed) is bool else None


def decide(actor, transcript, facts, new_facts, model_result):
    """Return (result, facts, route_match, end_call, stage)."""
    if actor == 'Raju':
        return model_result, new_facts, None, False, 'raju'
    stage = facts.get('_v18_stage','willingness')
    result = dict(model_result)
    result['language'] = result.get('language') if result.get('language') in ('hi','te','en') else 'hi'
    end = False
    match = None
    if stage == 'willingness':
        willing = willingness(transcript, new_facts.get('accepted'))
        if willing is False:
            new_facts['accepted']=False
            result['reply']=f'कोई बात नहीं {actor} जी। आपका समय देने के लिए धन्यवाद। नमस्कार।'
            end=True;stage='declined'
        elif willing is True:
            new_facts['accepted']=True
            stage='route'
            result['reply']=f'बहुत धन्यवाद {actor} जी। आप अभी किस लोकेशन या रूट की तरफ जा रहे हैं?'
        else:
            result['reply']=f'{actor} जी, क्या आप राजू जी की कुछ डिलीवरी में मदद कर पाएंगे?'
    elif stage == 'route':
        spoken=facts.get('_verified_route_localities') or []
        destination=facts.get('_extracted_destination')
        if destination:
            new_facts['destination']=destination
            new_facts['route_description']=destination
        if destination and not spoken:
            result['reply']=reply_in_language(result['language'],
                f'{actor} जी, आपका गंतव्य {destination} दर्ज है, लेकिन पार्सल स्थान सत्यापित नहीं हैं। कृपया नज़दीकी डिलीवरी क्षेत्र बताइए।',
                f'{actor}, I recorded {destination}, but parcel locations are not verified for it. Which delivery area is on your route?',
                f'{actor} గారు, {destination} నమోదు చేశాను. కానీ పార్సెల్ ప్రాంతం ధృవీకరించబడలేదు. మీ మార్గంలో ఉన్న డెలివరీ ప్రాంతం చెప్పండి.')
        elif not spoken:
            result['reply']=reply_in_language(result['language'],
                f'{actor} जी, आप किस जगह जा रहे हैं? कृपया जगह का नाम बताइए।',
                f'{actor}, which destination are you heading toward? Please tell me the place name.',
                f'{actor} గారు, మీరు ఏ ప్రాంతానికి వెళ్తున్నారు? ఆ ప్రాంతం పేరు చెప్పండి.')

        if spoken:
            # Match by exact pending-manifest locality. This is a locality candidate,
            # NOT verified proximity or a driving-route claim.
            from app.api import v11_route
            ctx = v11_route.context(x_dispatcher_token=None)
            pending = [p for p in ctx['parcels'] if p['status'] == 'pending']
            match = {'matched': [{'id':p['id'], 'locality':p['locality']} for p in pending if p['locality'] in spoken],
                     'route': spoken, 'measurement': 'manifest_locality_match_only'}
            ids=[p['id'] for p in match['matched']]
            new_facts['route_localities']=spoken
            new_facts['route_candidate_ids']=ids
            new_facts['match_basis']='manifest_locality_match_only'
            if ids:
                stage='eta'
                result['reply']=reply_in_language(result['language'],
                    f'{actor} जी, आपके बताए क्षेत्र में {len(ids)} पार्सल दर्ज हैं। यह रूट दूरी की पुष्टि नहीं है। राजू जी के पास कितने मिनट में पहुँचेंगे?',
                    f'{actor}, {len(ids)} pending parcel(s) are listed in that delivery area. Route distance is not verified. How many minutes until you reach Raju?',
                    f'{actor} గారు, ఆ డెలివరీ ప్రాంతంలో {len(ids)} పార్సెల్‌లు ఉన్నాయి. రూట్ దూరం నిర్ధారించలేదు. రాజు దగ్గరకు ఎన్ని నిమిషాల్లో చేరుకుంటారు?')
            else:
                result['reply']=reply_in_language(result['language'],
                    f'{actor} जी, उस क्षेत्र में कोई पेंडिंग पार्सल नहीं मिला। क्या दूसरा डिलीवरी क्षेत्र बताएंगे?',
                    f'{actor}, no pending parcels are listed in that area. Is there another delivery area on your route?',
                    f'{actor} గారు, ఆ ప్రాంతంలో పెండింగ్ పార్సెల్‌లు లేవు. మీ మార్గంలో మరొక డెలివరీ ప్రాంతం ఉందా?')
        else:
            pass
    elif stage == 'eta':
        eta=extract_eta(transcript)
        if eta is None:
            # Model can extract spoken ETA expressed in other language, but must be supported by speech.
            candidate=new_facts.get('eta_minutes')
            if type(candidate) is int and 1<=candidate<=240 and any(w in transcript.casefold() for w in ('minute','min','मिनट','నిమిష','पहुंच','पहुँच','reach')):
                eta=candidate
        if eta is None:
            result['reply']=reply_in_language(result['language'],
                f'{actor} जी, राजू जी के पास पहुँचने में लगभग कितने मिनट लगेंगे?',
                f'{actor}, about how many minutes until you reach Raju?',
                f'{actor} గారు, రాజు దగ్గరకు చేరుకోవడానికి ఎన్ని నిమిషాలు పడుతుంది?')
        else:
            new_facts['eta_minutes']=eta
            stage='consent'
            result['reply']=(f'धन्यवाद {actor} जी। आपका {eta} मिनट का पिकअप टाइम रिकॉर्ड कर लिया है। '
                             'पार्सल की जानकारी आपके ड्राइवर ऐप में साझा की जाएगी। '
                             'क्या आपकी अनुमति से मैं कॉल समाप्त कर सकती हूँ?')
    elif stage == 'consent':
        if consent_yes(transcript):
            new_facts['_v18_end_permission']=True
            result['reply']=f'आपके सहयोग के लिए धन्यवाद {actor} जी। सुरक्षित यात्रा कीजिए। नमस्कार।'
            end=True;stage='completed'
        else:
            result['reply']=f'{actor} जी, क्या आपको कोई और जानकारी चाहिए, या मैं आपकी अनुमति से कॉल समाप्त कर सकती हूँ?'
    new_facts['_v18_stage']=stage
    result['end_call']=end
    result['ready_to_close']=end
    return result,new_facts,match,end,stage
