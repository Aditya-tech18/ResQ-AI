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
    s = text.casefold().replace('०','0').replace('१','1').replace('२','2').replace('३','3').replace('४','4').replace('५','5').replace('६','6').replace('७','7').replace('८','8').replace('९','9')
    # Avoid interpreting an address number as ETA; require time context.
    m = re.search(r'\b(\d{1,3})\s*(?:min(?:ute)?s?|मिनट|నిమిషా(?:లు)?|minutes?)\b',s)
    if m:
        n=int(m.group(1))
        return n if 1 <= n <= 240 else None
    words={'एक':1,'दो':2,'तीन':3,'चार':4,'पांच':5,'पाँच':5,'छह':6,'सात':7,'आठ':8,'नौ':9,'दस':10,'पंद्रह':15,'बीस':20,'five':5,'ten':10,'eight':8,'fifteen':15,'twenty':20}
    if any(w in s for w in ('मिनट','minute','min ','నిమిష')):
        for word,n in words.items():
            if word in s: return n
    return None


def consent_yes(text):
    s=text.casefold().strip()
    if any(w in s for w in ('नहीं','नही','मत','रुको','रुकिए','wait','no ','not ','వద్దు')):return False
    return any(w in s for w in ('हाँ','हां','जी हाँ','बिल्कुल','बिलकुल','ठीक है','कर दीजिए','काट दीजिए','yes','okay','ok','sure','అవును','సరే','చేయండి'))


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
        spoken=v14_nearby.route_from_speech(transcript)
        if spoken:
            match=v14_nearby.nearby(spoken,radius_km=2.0)
            ids=[p['id'] for p in match['matched']]
            new_facts['route_localities']=spoken
            new_facts['route_candidate_ids']=ids
            new_facts['nearby_radius_km']=2.0
            if ids:
                stage='eta'
                result['reply']=(f'{actor} जी, आपके बताए रास्ते के लगभग 2 किलोमीटर के दायरे में '
                                 f'राजू जी के {len(ids)} पार्सल मिल रहे हैं। '
                                 'आप राजू जी के पास कितने मिनट में पहुँच सकते हैं?')
            else:
                result['reply']=(f'{actor} जी, आपके बताए रास्ते के 2 किलोमीटर के दायरे में '
                                 'अभी कोई मेल खाता पार्सल नहीं मिला। क्या आप किसी दूसरे रूट पर जा रहे हैं?')
        else:
            result['reply']=f'{actor} जी, कृपया अपना अगला रूट या लोकेशन बताइए, ताकि मैं पार्सल मिलान कर सकूँ।'
    elif stage == 'eta':
        eta=extract_eta(transcript)
        if eta is None:
            # Model can extract spoken ETA expressed in other language, but must be supported by speech.
            candidate=new_facts.get('eta_minutes')
            if type(candidate) is int and 1<=candidate<=240 and any(w in transcript.casefold() for w in ('minute','min','मिनट','నిమిష','पहुंच','पहुँच','reach')):
                eta=candidate
        if eta is None:
            result['reply']=f'{actor} जी, राजू जी के पास पहुँचने में लगभग कितने मिनट लगेंगे?'
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
