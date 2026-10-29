from datetime import UTC, datetime, timedelta

import pytest

from app.clients import payments_client
from app.errors import ApiError

valid_member = {
    "firstName": "Jane",
    "lastName": "Doe",
    "email": "jane@example.com",
    "membershipPlan": "PREMIUM",
}


def create_member(client, **overrides):
    payload = {**valid_member, **overrides}
    return client.post("/api/members", json=payload)


def stub_charge(monkeypatch, error=None):
    calls = []

    def fake_charge(payload):
        calls.append(payload)
        if error is not None:
            raise error
        return {"id": 1, "status": "SUCCESS", "amount": payload["amount"]}

    monkeypatch.setattr(payments_client, "charge", fake_charge)
    return calls


def test_health_returns_ok(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_create_member_returns_the_given_fields(client):
    response = create_member(client)

    assert response.status_code == 201
    body = response.get_json()
    assert body["firstName"] == "Jane"
    assert body["lastName"] == "Doe"
    assert body["email"] == "jane@example.com"
    assert body["membershipPlan"] == "PREMIUM"
    assert body["status"] == "ACTIVE"
    assert isinstance(body["id"], int)


def test_create_member_defaults_plan_and_status(client):
    response = client.post(
        "/api/members",
        json={"firstName": "John", "lastName": "Smith", "email": "john@example.com"},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["membershipPlan"] == "BASIC"
    assert body["status"] == "ACTIVE"


def test_create_member_rejects_a_missing_required_field(client):
    response = client.post(
        "/api/members",
        json={"lastName": "Doe", "email": "missing-first@example.com"},
    )

    assert response.status_code == 400
    assert "firstName" in response.get_json()["message"]


def test_create_member_rejects_an_invalid_email(client):
    response = client.post(
        "/api/members",
        json={"firstName": "Jane", "lastName": "Doe", "email": "not-an-email"},
    )

    assert response.status_code == 400


def test_create_member_rejects_a_duplicate_email(client):
    create_member(client)

    response = create_member(client, firstName="Other")

    assert response.status_code == 400
    assert "unique" in response.get_json()["message"]


def test_list_members(client):
    create_member(client)

    response = client.get("/api/members")

    assert response.status_code == 200
    body = response.get_json()
    assert len(body) == 1
    assert body[0]["email"] == valid_member["email"]


def test_list_members_returns_empty_list(client):
    response = client.get("/api/members")

    assert response.status_code == 200
    assert response.get_json() == []


def test_get_member_by_id(client):
    created = create_member(client).get_json()

    response = client.get(f"/api/members/{created['id']}")

    assert response.status_code == 200
    assert response.get_json()["email"] == valid_member["email"]


def test_get_member_returns_404_for_unknown_id(client):
    response = client.get("/api/members/999999")

    assert response.status_code == 404


def test_update_member(client):
    created = create_member(client).get_json()

    response = client.put(f"/api/members/{created['id']}", json={"status": "SUSPENDED"})

    assert response.status_code == 200
    assert response.get_json()["status"] == "SUSPENDED"


def test_update_member_returns_404_for_unknown_id(client):
    response = client.put("/api/members/999999", json={"status": "SUSPENDED"})

    assert response.status_code == 404


def test_delete_member(client):
    created = create_member(client).get_json()

    response = client.delete(f"/api/members/{created['id']}")

    assert response.status_code == 204
    assert client.get(f"/api/members/{created['id']}").status_code == 404


def test_delete_member_returns_404_for_unknown_id(client):
    response = client.delete("/api/members/999999")

    assert response.status_code == 404


def test_unknown_route_returns_404(client):
    response = client.get("/api/not-a-real-route")

    assert response.status_code == 404
    assert "message" in response.get_json()


@pytest.mark.parametrize(
    ("plan", "price"),
    [("BASIC", 29.99), ("STANDARD", 49.99), ("PREMIUM", 79.99)],
)
def test_renew_charges_the_current_plan_price_with_the_renewal_reason(
    client, monkeypatch, plan, price
):
    calls = stub_charge(monkeypatch)
    created = create_member(client, membershipPlan=plan).get_json()

    response = client.post(f"/api/members/{created['id']}/renew")

    assert response.status_code == 200
    assert calls == [
        {"memberId": created["id"], "amount": price, "reason": f"{plan} plan renewal"}
    ]


def test_renew_returns_the_member_with_a_renewal_date_30_days_ahead(client, monkeypatch):
    stub_charge(monkeypatch)
    created = create_member(client).get_json()
    assert created["renewalDate"] is None

    response = client.post(f"/api/members/{created['id']}/renew")

    assert response.status_code == 200
    body = response.get_json()
    expected = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    assert body["renewalDate"] == expected
    assert set(body) == set(created)
    for field in ("id", "firstName", "lastName", "email", "phone", "membershipPlan", "status"):
        assert body[field] == created[field]

    stored = client.get(f"/api/members/{created['id']}").get_json()
    assert stored["renewalDate"] == expected


def test_renew_returns_402_and_leaves_renewal_date_unchanged_when_the_charge_is_declined(
    client, monkeypatch
):
    stub_charge(monkeypatch, error=ApiError(402, "Payment was declined"))
    created = create_member(client).get_json()
    assert created["renewalDate"] is None

    response = client.post(f"/api/members/{created['id']}/renew")

    assert response.status_code == 402
    body = response.get_json()
    assert "renewalDate" not in body
    assert body["message"] == "Payment was declined"

    stored = client.get(f"/api/members/{created['id']}").get_json()
    assert stored["renewalDate"] is None


def test_renew_returns_402_and_keeps_a_previously_stored_renewal_date(client, monkeypatch):
    stub_charge(monkeypatch)
    created = create_member(client).get_json()
    previous = client.post(f"/api/members/{created['id']}/renew").get_json()["renewalDate"]
    assert previous is not None

    stub_charge(monkeypatch, error=ApiError(402, "Payment was declined"))

    response = client.post(f"/api/members/{created['id']}/renew")

    assert response.status_code == 402
    assert "renewalDate" not in response.get_json()

    stored = client.get(f"/api/members/{created['id']}").get_json()
    assert stored["renewalDate"] == previous


def test_renew_returns_503_and_leaves_renewal_date_unchanged_when_payments_is_unreachable(
    client, monkeypatch
):
    stub_charge(monkeypatch, error=ApiError(503, "Payments service is unavailable"))
    created = create_member(client).get_json()
    assert created["renewalDate"] is None

    response = client.post(f"/api/members/{created['id']}/renew")

    assert response.status_code == 503

    stored = client.get(f"/api/members/{created['id']}").get_json()
    assert stored["renewalDate"] is None


def test_renew_returns_404_without_calling_payments_for_an_unknown_member(client, monkeypatch):
    calls = stub_charge(monkeypatch)

    response = client.post("/api/members/999999/renew")

    assert response.status_code == 404
    assert calls == []
