from decimal import Decimal

import pytest

from app.clients import payments_client

valid_member = {
    "firstName": "Jane",
    "lastName": "Doe",
    "email": "tier@example.com",
}


def create_member(client, **overrides):
    payload = {**valid_member, **overrides}
    response = client.post("/api/members", json=payload)
    assert response.status_code == 201
    return response.get_json()


def stub_spend(monkeypatch, value):
    spend = None if value is None else Decimal(str(value))
    monkeypatch.setattr(payments_client, "fetch_spend", lambda member_id: spend)


@pytest.mark.parametrize(
    ("spend", "expected_tier"),
    [
        (0, "BRONZE"),
        (99.99, "BRONZE"),
        (-5, "BRONZE"),
        (100, "SILVER"),
        (499.99, "SILVER"),
        (500, "GOLD"),
        (1000, "GOLD"),
    ],
)
def test_tier_boundaries(client, monkeypatch, spend, expected_tier):
    member = create_member(client)
    stub_spend(monkeypatch, spend)

    response = client.get(f"/api/members/{member['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == expected_tier
    assert body["spend"] == pytest.approx(float(spend))


def test_unavailable_fallback_returns_200(client, monkeypatch):
    member = create_member(client)
    stub_spend(monkeypatch, None)

    response = client.get(f"/api/members/{member['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == "UNAVAILABLE"
    assert body["spend"] is None


def test_member_response_keeps_existing_fields(client, monkeypatch):
    member = create_member(client)
    stub_spend(monkeypatch, "123.45")

    body = client.get(f"/api/members/{member['id']}").get_json()

    for field in (
        "id",
        "firstName",
        "lastName",
        "email",
        "phone",
        "membershipPlan",
        "status",
        "joinedAt",
        "createdAt",
        "updatedAt",
    ):
        assert field in body
    assert body["tier"] == "SILVER"
    assert body["spend"] == pytest.approx(123.45)


def test_members_list_has_no_tier_or_spend(client, monkeypatch):
    create_member(client)
    stub_spend(monkeypatch, "500")

    response = client.get("/api/members")

    assert response.status_code == 200
    body = response.get_json()
    assert len(body) == 1
    assert "tier" not in body[0]
    assert "spend" not in body[0]


def test_unknown_member_returns_404(client, monkeypatch):
    calls = []

    def _fetch_spend(member_id):
        calls.append(member_id)
        return Decimal("0")

    monkeypatch.setattr(payments_client, "fetch_spend", _fetch_spend)

    response = client.get("/api/members/999999")

    assert response.status_code == 404
    assert calls == []
