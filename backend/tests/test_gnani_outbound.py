"""Unit tests for the configurable Gnani outbound adapter."""

import httpx
import pytest

from app.integrations.gnani_outbound import (
    GnaniCallError,
    GnaniConfigurationError,
    GnaniOutboundClient,
    GnaniOutboundConfig,
)


def test_rejects_insecure_endpoint():
    with pytest.raises(GnaniConfigurationError):
        GnaniOutboundClient(
            GnaniOutboundConfig(
                endpoint="http://example.test/calls",
                api_key="test-key",
            )
        )


def test_rejects_missing_key():
    with pytest.raises(GnaniConfigurationError):
        GnaniOutboundClient(
            GnaniOutboundConfig(
                endpoint="https://example.test/calls",
                api_key="",
            )
        )


def test_successful_mock_call():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/calls"
        assert request.headers["Authorization"] == "Bearer test-key"

        return httpx.Response(
            200,
            json={"call_id": "mock-call-123"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = GnaniOutboundClient(
            GnaniOutboundConfig(
                endpoint="https://example.test/calls",
                api_key="test-key",
            ),
            client=client,
        )

        result = adapter.initiate_call(
            payload={
                "phone_number": "+919999999999",
            },
            headers={
                "Authorization": "Bearer test-key",
            },
        )

    assert result["call_id"] == "mock-call-123"


def test_provider_error():
    def handler(request):
        return httpx.Response(503, json={"error": "unavailable"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = GnaniOutboundClient(
            GnaniOutboundConfig(
                endpoint="https://example.test/calls",
                api_key="test-key",
            ),
            client=client,
        )

        with pytest.raises(GnaniCallError):
            adapter.initiate_call(
                payload={"phone_number": "+919999999999"},
                headers={"Authorization": "Bearer test-key"},
            )
