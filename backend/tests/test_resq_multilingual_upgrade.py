import pytest
from app.api.resq_multilingual import detect_language, from_manifest, resolve_manifest_localities, RouteExtraction
from app.api.v18_logic import consent_yes, extract_eta

@pytest.mark.parametrize('text,expected',[
    ('నేను గోపాలపట్నం వైపు వెళ్తున్నాను','te'),('నేను వస్తున్నాను','te'),
    ('मैं जा रहा हूँ','hi'),('मुझे समय लगेगा','hi'),
    ('Heading to a new place','en'),('I can arrive','en'),
])
def test_language(text,expected):assert detect_language(text)==expected

@pytest.mark.parametrize('name', [f'Area {i:02d}' for i in range(1,31)])
def test_dynamic_manifest_names(name):
    assert from_manifest(f'I am heading toward {name}',[name])==name
    assert resolve_manifest_localities(name,[name])==[name]

@pytest.mark.parametrize('text', ['okay','sure','okay but wait','not yet','अभी नहीं','వద్దు','wait a moment','yes but wait'])
def test_ambiguous_consent_rejected(text):assert not consent_yes(text)

@pytest.mark.parametrize('text,expected', [('8 minutes',8),('१२ मिनट',12),('౧౫ నిమిషాలు',15),('five minutes',5),('पाँच मिनट',5),('ఎనిమిది నిమిషాలు',8)])
def test_eta(text,expected):assert extract_eta(text)==expected

def test_invalid_extraction_rejected():
    with pytest.raises(Exception):RouteExtraction(language='fr',destination='fake')
