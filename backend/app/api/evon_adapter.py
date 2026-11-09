"""Optional Evon integration boundary. Official request contract must be supplied/verified.

This module deliberately refuses to guess undocumented provider endpoints or schemas.
"""
import os
from urllib.parse import urlparse

class EvonConfigurationError(RuntimeError):
    pass

def evon_status() -> dict:
    endpoint = os.getenv("GNANI_EVON_ENDPOINT", "").strip()
    key = os.getenv("GNANI_EVON_API_KEY", "").strip()
    parsed = urlparse(endpoint)
    configured = bool(key and parsed.scheme == "https" and parsed.hostname)
    return {"configured": configured, "live_validated": False,
            "reason": "Evon contract and account entitlement require provider verification"}

def require_verified_evon_contract() -> None:
    raise EvonConfigurationError("Evon live extraction disabled: verify official endpoint, auth and payload schema before activation")
