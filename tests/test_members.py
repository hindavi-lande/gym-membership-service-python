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


class RecordedCharges(list):
    """Charges sent to the payments service, plus a way to make the fake fail."""

    def __init__(self):
        super().__init__()
        self.error = None

    def fail_with(self, error):
        self.error = error


@pytest.fixture()
def recorded_charges(monkeypatch):
    charges = RecordedCharges()

    def fake_charge(payload):
        charges.append(payload)
        if charges.error is not None:
            raise charges.error
        return {"status": "SUCCESS"}

    monkeypatch.setattr(payments_client, "charge", fake_charge)
    return charges


@pytest.mark.parametrize(
    ("plan", "price"),
    [("BASIC", 29.99), ("STANDARD", 49.99), ("PREMIUM", 79.99)],
)
def test_renew_charges_the_current_plan_price_and_reason(client, recorded_charges, plan, price):
    created = create_member(client, membershipPlan=plan).get_json()

    response = client.post(f"/api/members/{created['id']}/renew")

    assert response.status_code == 200
    assert len(recorded_charges) == 1
    assert recorded_charges[0]["memberId"] == created["id"]
    assert recorded_charges[0]["amount"] == price
    assert recorded_charges[0]["reason"] == f"{plan} plan renewal"


def test_renew_returns_200_and_sets_renewal_date(client, recorded_charges):
    created = create_member(client).get_json()
    expected = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()

    response = client.post(f"/api/members/{created['id']}/renew")

    assert response.status_code == 200
    assert response.get_json()["renewalDate"] == expected
    assert client.get(f"/api/members/{created['id']}").get_json()["renewalDate"] == expected


def test_member_responses_expose_renewal_date(client, recorded_charges):
    created = create_member(client).get_json()
    assert created["renewalDate"] is None

    client.post(f"/api/members/{created['id']}/renew")

    listed = client.get("/api/members")
    assert listed.status_code == 200
    assert listed.get_json()[0]["renewalDate"] is not None
    assert client.get(f"/api/members/{created['id']}").get_json()["renewalDate"] == (
        listed.get_json()[0]["renewalDate"]
    )


def test_renew_returns_402_and_leaves_renewal_date_unchanged(client, recorded_charges):
    created = create_member(client).get_json()

    recorded_charges.fail_with(ApiError(402, "payment declined"))
    response = client.post(f"/api/members/{created['id']}/renew")

    assert response.status_code == 402
    assert response.get_json()["message"] == "payment declined"
    fetched = client.get(f"/api/members/{created['id']}")
    assert fetched.get_json()["renewalDate"] is None


def test_renew_returns_503_and_leaves_renewal_date_unchanged(client, recorded_charges):
    created = create_member(client).get_json()

    recorded_charges.fail_with(ApiError(503, "payments service unavailable"))
    response = client.post(f"/api/members/{created['id']}/renew")

    assert response.status_code == 503
    assert response.get_json()["message"] == "payments service unavailable"
    fetched = client.get(f"/api/members/{created['id']}")
    assert fetched.get_json()["renewalDate"] is None


def test_renew_returns_404_and_does_not_call_payments(client, recorded_charges):
    response = client.post("/api/members/999999/renew")

    assert response.status_code == 404
    assert recorded_charges == []


def test_a_suspended_member_can_renew(client, recorded_charges):
    created = create_member(client).get_json()
    client.put(f"/api/members/{created['id']}", json={"status": "SUSPENDED"})

    response = client.post(f"/api/members/{created['id']}/renew")

    assert response.status_code == 200
    assert response.get_json()["status"] == "SUSPENDED"
    assert len(recorded_charges) == 1
