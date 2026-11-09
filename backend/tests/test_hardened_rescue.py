from app.api.v18_logic import consent_yes, extract_eta, reply_in_language
import pytest

@pytest.mark.parametrize('utterance', ['okay', 'sure', 'okay but wait', 'yes but wait', 'हाँ लेकिन रुको', 'not yet', 'సరే కానీ ఆగండి', 'कॉल मत काटिए'])
def test_ambiguous_consent_is_not_permission(utterance):
    assert consent_yes(utterance) is False

@pytest.mark.parametrize('utterance', ['yes end the call', 'please end the call', 'कॉल समाप्त कर दीजिए', 'కాల్ ముగించండి'])
def test_explicit_permission(utterance):
    assert consent_yes(utterance) is True

@pytest.mark.parametrize('utterance, expected', [('8 minutes',8),('आठ मिनट',8),('ఎనిమిది నిమిషాలు',8),('౮ నిమిషాలు',8),('100 parcels',None),('at junction 12',None)])
def test_eta(utterance,expected):
    assert extract_eta(utterance)==expected

def test_language():
    assert reply_in_language('te','hi','en','telugu')=='telugu'
