import pytest

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


@pytest.fixture()
def payments_calls(monkeypatch):
    calls = []

    def fake_merge_payments(from_member_id, to_member_id):
        calls.append((from_member_id, to_member_id))
        return {"movedCount": 0}

    monkeypatch.setattr("app.clients.payments_client.merge_payments", fake_merge_payments)
    return calls


def merge_member(client, to_member_id, from_member_id):
    return client.post(
        f"/api/members/{to_member_id}/merge",
        json={"fromMemberId": from_member_id},
    )


def create_duplicate_pair(client):
    kept = create_member(client).get_json()
    duplicate = create_member(client, email="duplicate@example.com").get_json()
    return kept, duplicate


def test_merge_returns_the_kept_member_and_removes_the_duplicate(client, payments_calls):
    kept, duplicate = create_duplicate_pair(client)

    response = merge_member(client, kept["id"], duplicate["id"])

    assert response.status_code == 200
    assert response.get_json()["id"] == kept["id"]
    assert client.get(f"/api/members/{duplicate['id']}").status_code == 404


def test_merge_leaves_the_kept_member_details_unchanged(client, payments_calls):
    kept, duplicate = create_duplicate_pair(client)
    before = client.get(f"/api/members/{kept['id']}").get_json()

    response = merge_member(client, kept["id"], duplicate["id"])

    assert response.status_code == 200
    assert client.get(f"/api/members/{kept['id']}").get_json() == before


def test_merge_sends_the_duplicate_as_from_and_kept_as_to(client, payments_calls):
    kept, duplicate = create_duplicate_pair(client)

    response = merge_member(client, kept["id"], duplicate["id"])

    assert response.status_code == 200
    assert payments_calls == [(duplicate["id"], kept["id"])]


def test_merge_rejects_merging_an_account_into_itself(client, payments_calls):
    member = create_member(client).get_json()
    before = client.get(f"/api/members/{member['id']}").get_json()

    response = merge_member(client, member["id"], member["id"])

    assert response.status_code == 400
    assert payments_calls == []
    assert client.get(f"/api/members/{member['id']}").get_json() == before


def test_merge_returns_404_for_a_missing_kept_account(client, payments_calls):
    duplicate = create_member(client).get_json()

    response = merge_member(client, 999999, duplicate["id"])

    assert response.status_code == 404
    assert "999999" in response.get_json()["message"]
    assert payments_calls == []
    assert client.get(f"/api/members/{duplicate['id']}").status_code == 200


def test_merge_returns_404_for_a_missing_duplicate_account(client, payments_calls):
    kept = create_member(client).get_json()

    response = merge_member(client, kept["id"], 999999)

    assert response.status_code == 404
    assert "999999" in response.get_json()["message"]
    assert payments_calls == []
    assert client.get(f"/api/members/{kept['id']}").status_code == 200


def test_merge_returns_502_and_keeps_both_accounts_when_payments_fail(client, monkeypatch):
    kept, duplicate = create_duplicate_pair(client)
    kept_before = client.get(f"/api/members/{kept['id']}").get_json()
    duplicate_before = client.get(f"/api/members/{duplicate['id']}").get_json()

    def fake_merge_payments(from_member_id, to_member_id):
        raise ApiError(502, "Payments service failed to merge payments")

    monkeypatch.setattr("app.clients.payments_client.merge_payments", fake_merge_payments)

    response = merge_member(client, kept["id"], duplicate["id"])

    assert response.status_code == 502
    assert client.get(f"/api/members/{kept['id']}").get_json() == kept_before
    assert client.get(f"/api/members/{duplicate['id']}").get_json() == duplicate_before


def test_merge_rejects_invalid_from_member_id(client, payments_calls):
    kept, duplicate = create_duplicate_pair(client)
    invalid_bodies = [
        {},
        {"fromMemberId": "1"},
        {"fromMemberId": True},
        {"fromMemberId": 0},
    ]

    for body in invalid_bodies:
        response = client.post(f"/api/members/{kept['id']}/merge", json=body)
        assert response.status_code == 400

    assert payments_calls == []
    assert client.get(f"/api/members/{kept['id']}").status_code == 200
    assert client.get(f"/api/members/{duplicate['id']}").status_code == 200
