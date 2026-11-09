from pathlib import Path

def test_dispatcher_approval_auth_and_consent_guards_present():
 s=(Path(__file__).parents[1]/'app/api/v11_route.py').read_text()
 assert 'compare_digest' in s
 assert "facts.get('_v18_end_permission') is True" in s
 assert "facts.get('eta_minutes')" in s

def test_pickup_requires_assigned_state():
 s=(Path(__file__).parents[1]/'app/api/v11_route.py').read_text()
 assert "r['status']!='assigned'" in s
 assert 'BEGIN IMMEDIATE' in s

def test_no_credential_values_in_env_template():
 s=(Path(__file__).parents[1]/'.env.example').read_text()
 assert 'GEMINI_API_KEY=\n' in s
 assert 'RESQ_DISPATCHER_TOKEN=\n' in s
