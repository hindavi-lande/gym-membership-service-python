from datetime import UTC, datetime, timedelta

import pytest

from app.errors import ApiError
from app.services import member_service

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


class FakeCharge:
    def __init__(self):
        self.payloads = []
        self.error = None

    def __call__(self, payload):
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error
        return {"id": 1, "memberId": payload["memberId"], "type": "CHARGE", "status": "SUCCESS"}


def fake_charge():
    return FakeCharge()


def renew(client, member_id):
    return client.post(f"/api/members/{member_id}/renew")


@pytest.mark.parametrize(
    ("plan", "price"),
    [("BASIC", 29.99), ("STANDARD", 49.99), ("PREMIUM", 79.99)],
)
def test_renew_charges_plan_price_and_sets_renewal_date(client, monkeypatch, plan, price):
    charge = fake_charge()
    monkeypatch.setattr(member_service.payments_client, "charge", charge)
    created = create_member(client, membershipPlan=plan).get_json()

    response = renew(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["renewalDate"] == (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    assert charge.payloads == [
        {
            "memberId": created["id"],
            "amount": price,
            "reason": f"{plan} plan renewal",
        }
    ]
    assert body == client.get(f"/api/members/{created['id']}").get_json()


def test_renew_returns_402_and_leaves_renewal_date_unchanged(client, monkeypatch):
    charge = fake_charge()
    monkeypatch.setattr(member_service.payments_client, "charge", charge)
    created = create_member(client).get_json()

    first = renew(client, created["id"])
    assert first.status_code == 200
    previous_renewal_date = first.get_json()["renewalDate"]
    assert previous_renewal_date is not None

    charge.error = ApiError(402, "payment was declined")
    response = renew(client, created["id"])

    assert response.status_code == 402
    body = response.get_json()
    assert "not renewed" in body["message"]
    assert "renewalDate" not in body
    assert client.get(f"/api/members/{created['id']}").get_json()["renewalDate"] == (
        previous_renewal_date
    )


def test_renew_returns_503_when_payments_service_is_unreachable(client, monkeypatch):
    charge = fake_charge()
    charge.error = ApiError(503, "payments service is unavailable")
    monkeypatch.setattr(member_service.payments_client, "charge", charge)
    created = create_member(client).get_json()

    response = renew(client, created["id"])

    assert response.status_code == 503
    assert client.get(f"/api/members/{created['id']}").get_json()["renewalDate"] is None


def test_renew_returns_404_for_unknown_member_without_calling_payments(client, monkeypatch):
    charge = fake_charge()
    monkeypatch.setattr(member_service.payments_client, "charge", charge)

    response = renew(client, 999999)

    assert response.status_code == 404
    assert charge.payloads == []
