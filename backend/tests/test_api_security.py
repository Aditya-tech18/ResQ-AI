"""Regression tests for DispatchResolve API authentication."""

import os

os.environ["DISPATCH_DEV_API"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/v1/shipments", None),
        ("GET", "/api/v1/exceptions", None),
        ("POST", "/api/v1/detection/scan", {"limit": 10}),
    ],
)
def test_protected_api_requires_token(
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
        f"{method} {path} returned {response.status_code}: {response.text}"
    )


@pytest.mark.parametrize(
    "token",
    [
        "invalid.jwt.token",
        "abc123",
    ],
)
def test_me_rejects_invalid_token(client, token):
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_me_requires_token(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_health_remains_public(client):
    for path in ("/health", "/api/v1/status"):
        response = client.get(path)
        assert response.status_code == 200


def test_me_is_in_openapi(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/auth/me" in response.json()["paths"]
