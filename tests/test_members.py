from decimal import Decimal

import httpx
import pytest

from app.clients import payments_client
from app.clients.payments_client import get_spend as real_get_spend

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


PAYMENTS_SPEND_URL = "http://localhost:3001/api/payments/spend/1"


def _stub_spend(monkeypatch, spend):
    monkeypatch.setattr(payments_client, "get_spend", lambda member_id: spend)


def _response(payload=None, status_code=200, *, content=None):
    request = httpx.Request("GET", PAYMENTS_SPEND_URL)
    if content is not None:
        return httpx.Response(status_code, content=content, request=request)
    return httpx.Response(status_code, json=payload, request=request)


def _use_real_client_over_httpx(monkeypatch, response=None, error=None):
    monkeypatch.setattr(payments_client, "get_spend", real_get_spend)

    def fake_get(url, **kwargs):
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(httpx, "get", fake_get)


@pytest.mark.parametrize(
    ("spend", "expected_tier"),
    [
        (Decimal("0"), "BRONZE"),
        (Decimal("99.99"), "BRONZE"),
        (Decimal("-12.5"), "BRONZE"),
        (Decimal("100"), "SILVER"),
        (Decimal("499.99"), "SILVER"),
        (Decimal("500"), "GOLD"),
        (Decimal("1250.75"), "GOLD"),
    ],
)
def test_member_detail_tier_boundaries(client, monkeypatch, spend, expected_tier) -> None:
    _stub_spend(monkeypatch, spend)
    created = create_member(client).get_json()

    response = client.get(f"/api/members/{created['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == expected_tier
    assert body["spend"] == float(spend)


def test_member_detail_includes_spend(client, monkeypatch) -> None:
    _stub_spend(monkeypatch, Decimal("149.99"))
    created = create_member(client).get_json()

    response = client.get(f"/api/members/{created['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["spend"] == 149.99
    assert body["tier"] == "SILVER"
    assert body["email"] == valid_member["email"]


def test_member_detail_falls_back_to_unavailable_on_payments_timeout(client, monkeypatch) -> None:
    created = create_member(client).get_json()
    _use_real_client_over_httpx(monkeypatch, error=httpx.TimeoutException("timed out"))

    response = client.get(f"/api/members/{created['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == "UNAVAILABLE"
    assert body["spend"] is None


def test_member_detail_falls_back_to_unavailable_on_connection_failure(
    client, monkeypatch
) -> None:
    created = create_member(client).get_json()
    _use_real_client_over_httpx(monkeypatch, error=httpx.ConnectError("connection refused"))

    response = client.get(f"/api/members/{created['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == "UNAVAILABLE"
    assert body["spend"] is None


def test_member_detail_falls_back_to_unavailable_on_error_status(client, monkeypatch) -> None:
    created = create_member(client).get_json()
    _use_real_client_over_httpx(
        monkeypatch, _response({"message": "boom"}, status_code=500)
    )

    response = client.get(f"/api/members/{created['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == "UNAVAILABLE"
    assert body["spend"] is None


def test_member_detail_falls_back_to_unavailable_on_malformed_response(client, monkeypatch) -> None:
    created = create_member(client).get_json()
    _use_real_client_over_httpx(monkeypatch, _response(content=b"not-json"))

    response = client.get(f"/api/members/{created['id']}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["tier"] == "UNAVAILABLE"
    assert body["spend"] is None


def test_member_list_does_not_include_tier_or_spend(client, monkeypatch) -> None:
    _stub_spend(monkeypatch, Decimal("149.99"))
    create_member(client)

    response = client.get("/api/members")

    assert response.status_code == 200
    items = response.get_json()
    assert len(items) == 1
    for item in items:
        assert "tier" not in item
        assert "spend" not in item


def test_create_and_update_responses_do_not_include_tier_or_spend(client, monkeypatch) -> None:
    _stub_spend(monkeypatch, Decimal("149.99"))

    created = create_member(client)

    assert created.status_code == 201
    create_body = created.get_json()
    assert "tier" not in create_body
    assert "spend" not in create_body

    updated = client.put(
        f"/api/members/{create_body['id']}", json={"status": "SUSPENDED"}
    )

    assert updated.status_code == 200
    update_body = updated.get_json()
    assert "tier" not in update_body
    assert "spend" not in update_body
