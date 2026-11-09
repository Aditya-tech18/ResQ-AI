from fastapi.testclient import TestClient

from app.api.v6_dashboard import app


def test_dashboard_is_available_from_loopback():
    client = TestClient(app, client=("127.0.0.1", 50000))

    response = client.get("/")

    assert response.status_code == 200


def test_dashboard_rejects_non_loopback_clients():
    client = TestClient(app, client=("203.0.113.10", 50000))

    response = client.get("/")

    assert response.status_code == 403
