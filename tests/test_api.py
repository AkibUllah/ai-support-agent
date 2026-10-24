import pytest
from fastapi.testclient import TestClient

from support_agent.api.main import create_app


@pytest.fixture
def client(settings, service):
    with TestClient(
        create_app(settings.model_copy(update={"admin_api_key": "test-admin-key"}), service)
    ) as c:
        yield c


def _login(client, customer="C001"):
    body = client.post("/api/sessions", json={"customer_id": customer}).json()
    return body["session_id"], {"Authorization": f"Bearer {body['token']}"}


def test_health_and_tools(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and "initiate_refund" in health["tools"]
    assert len(client.get("/api/tools").json()) == 8


def test_customers_are_masked(client):
    customers = client.get("/api/customers").json()
    assert customers[0]["phone_masked"] == "017*****101"
    assert "phone" not in customers[0]


def test_session_and_message_flow_returns_trace(client):
    sid, auth = _login(client)
    res = client.post(
        f"/api/sessions/{sid}/messages", json={"text": "Where is HO-10024?"}, headers=auth
    )
    assert res.status_code == 200
    body = res.json()
    assert "Padma Courier" in body["reply"]
    assert body["trace"][0]["name"] == "track_shipment" and body["trace"][0]["status"] == "ok"
    history = client.get(f"/api/sessions/{sid}", headers=auth).json()
    assert history["customer"]["id"] == "C001" and len(history["turns"]) == 1


def test_auth_is_required_and_bound_to_the_session(client):
    sid, auth = _login(client, "C001")
    other_sid, other_auth = _login(client, "C003")
    assert client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"}).status_code == 401
    assert (
        client.post(
            f"/api/sessions/{sid}/messages",
            json={"text": "hi"},
            headers={"Authorization": "Bearer nope"},
        ).status_code
        == 401
    )
    # A valid token for another session does not open this one.
    assert client.get(f"/api/sessions/{sid}", headers=other_auth).status_code == 401
    assert client.get(f"/api/sessions/{other_sid}", headers=other_auth).status_code == 200


def test_validation_errors(client):
    assert client.post("/api/sessions", json={"customer_id": "X1"}).status_code == 422
    assert client.post("/api/sessions", json={"customer_id": "C999"}).status_code == 404
    sid, auth = _login(client)
    assert (
        client.post(f"/api/sessions/{sid}/messages", json={"text": ""}, headers=auth).status_code
        == 422
    )


def test_admin_handoff_queue(client):
    sid, auth = _login(client, "C004")
    client.post(
        f"/api/sessions/{sid}/messages", json={"text": "I want a real person"}, headers=auth
    )
    assert client.get("/api/admin/handoffs").status_code == 403
    queue = client.get("/api/admin/handoffs", headers={"X-Admin-Key": "test-admin-key"}).json()
    assert queue["sessions"][0]["id"] == sid and queue["tickets"]
