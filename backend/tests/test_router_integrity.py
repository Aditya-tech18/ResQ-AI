"""Route integrity and authentication regression tests."""

import os
import warnings

os.environ["DISPATCH_DEV_API"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_no_duplicate_operation_ids(client):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app.openapi_schema = None
        response = client.get("/openapi.json")

    assert response.status_code == 200

    duplicate_warnings = [
        str(item.message) for item in caught if "Duplicate Operation ID" in str(item.message)
    ]

    assert not duplicate_warnings, duplicate_warnings


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/v1/shipments", None),
        ("POST", "/api/v1/shipments", {}),
        ("GET", "/api/v1/exceptions", None),
        ("POST", "/api/v1/exceptions", {}),
        ("POST", "/api/v1/detection/scan", {"limit": 10}),
    ],
)
def test_business_apis_require_auth(
    client,
    method,
    path,
    payload,
):
    response = client.request(
        method,
        path,
        json=payload,
    )

    assert response.status_code == 401, (
        method,
        path,
        response.status_code,
        response.text,
    )


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/api/v1/status",
    ],
)
def test_public_health_endpoints(client, path):
    response = client.get(path)
    assert response.status_code == 200


def test_auth_me_requires_token(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_login_endpoint_still_registered(client):
    schema = client.get("/openapi.json").json()
    assert "/api/v1/auth/login" in schema["paths"]
