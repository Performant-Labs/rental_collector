from fastapi.testclient import TestClient

from dashboard.app.main import app

client = TestClient(app)


def test_health_endpoint_returns_200():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_home_route_returns_200():
    response = client.get("/")

    assert response.status_code == 200


def test_home_uses_template_response():
    response = client.get("/")

    assert response.template.name == "index.html"
    assert "request" in response.context
