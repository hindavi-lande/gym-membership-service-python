import urllib.error

from app.clients import payments
from app.services import tier_service

MEMBER_PAYLOAD = {
    "firstName": "Jane",
    "lastName": "Doe",
    "email": "jane@example.com",
}

SPEND_URL = "http://localhost:3001/api/payments/member/1/spend"


def create_member(client):
    response = client.post("/api/members", json=MEMBER_PAYLOAD)
    return response.get_json()


def stub_spend(monkeypatch, spend):
    monkeypatch.setattr(payments, "_fetch_json", lambda url, timeout: spend)


def stub_failure(monkeypatch, error):
    def _raise(*args, **kwargs):
        raise error

    monkeypatch.setattr(payments, "_fetch_json", _raise)


def test_tier_boundaries(client, stub_payments_client):
    member = create_member(client)

    cases = [
        (0, "BRONZE"),
        (9999, "BRONZE"),
        (10000, "SILVER"),
        (49999, "SILVER"),
        (50000, "GOLD"),
        (50001, "GOLD"),
    ]

    for spend, expected_tier in cases:
        stub_spend(stub_payments_client, spend)

        response = client.get(f"/api/members/{member['id']}")

        assert response.status_code == 200
        body = response.get_json()
        assert body["tier"] == expected_tier
        assert body["spend"] == spend


def test_negative_spend_is_bronze(client, stub_payments_client):
    member = create_member(client)
    stub_spend(stub_payments_client, -1500)

    response = client.get(f"/api/members/{member['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == "BRONZE"
    assert body["spend"] == -1500


def test_profile_falls_back_to_unavailable_on_timeout(client, stub_payments_client):
    member = create_member(client)
    stub_failure(stub_payments_client, TimeoutError("timed out"))

    response = client.get(f"/api/members/{member['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == "UNAVAILABLE"
    assert body["spend"] is None


def test_profile_falls_back_to_unavailable_on_connection_failure(client, stub_payments_client):
    member = create_member(client)
    stub_failure(
        stub_payments_client,
        urllib.error.URLError(ConnectionRefusedError("Connection refused")),
    )

    response = client.get(f"/api/members/{member['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == "UNAVAILABLE"
    assert body["spend"] is None


def test_profile_falls_back_to_unavailable_on_error_status(client, stub_payments_client):
    member = create_member(client)
    stub_failure(
        stub_payments_client,
        urllib.error.HTTPError(SPEND_URL, 500, "Internal Server Error", None, None),
    )

    response = client.get(f"/api/members/{member['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == "UNAVAILABLE"
    assert body["spend"] is None


def test_profile_falls_back_to_unavailable_on_malformed_response(client, stub_payments_client):
    member = create_member(client)
    stub_spend(stub_payments_client, {"unexpected": 1})

    response = client.get(f"/api/members/{member['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == "UNAVAILABLE"
    assert body["spend"] is None


def test_members_list_is_unchanged_by_tiers(client, stub_payments_client):
    member = create_member(client)
    stub_spend(stub_payments_client, 50000)

    list_response = client.get("/api/members")

    assert list_response.status_code == 200
    items = list_response.get_json()
    assert len(items) == 1
    assert "tier" not in items[0]
    assert "spend" not in items[0]
    assert set(items[0]) == {
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
    }

    detail_response = client.get(f"/api/members/{member['id']}")

    assert detail_response.status_code == 200
    body = detail_response.get_json()
    assert body["tier"] == "GOLD"
    assert body["spend"] == 50000


def test_unknown_member_profile_returns_404_without_calling_payments(client, stub_payments_client):
    calls = []

    def _record(*args, **kwargs):
        calls.append(args)
        return 0

    stub_payments_client.setattr(payments, "_fetch_json", _record)

    response = client.get("/api/members/999999")

    assert response.status_code == 404
    assert calls == []


def test_tier_for_spend_thresholds():
    assert tier_service.tier_for_spend(None) == "UNAVAILABLE"
    assert tier_service.tier_for_spend(-1500) == "BRONZE"
    assert tier_service.tier_for_spend(0) == "BRONZE"
    assert tier_service.tier_for_spend(9999) == "BRONZE"
    assert tier_service.tier_for_spend(10000) == "SILVER"
    assert tier_service.tier_for_spend(49999) == "SILVER"
    assert tier_service.tier_for_spend(50000) == "GOLD"
    assert tier_service.tier_for_spend(50001) == "GOLD"
