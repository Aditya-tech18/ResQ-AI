from app.api.resq_multilingual import detect_language
from app.api import v11_route

def test_language_hints():
    assert detect_language('Gopalapatnam','te-IN')=='te'
    assert detect_language('Gopalapatnam','hi-IN')=='hi'
    assert detect_language('Gopalapatnam','en-US')=='en'
    assert detect_language('నేను వెళ్తున్నాను','en-US')=='te'

def test_intro_no_header_object_crash(monkeypatch):
    monkeypatch.setattr(v11_route,'context',lambda x_dispatcher_token=None: {'incident':{'location':'Test junction'},'pending':2})
    result=v11_route.intro('Suresh')
    assert 'Test junction' in result['text']
