import pytest

from app.clients import payments_client
from app.errors import ApiError
from app.extensions import db

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


def stub_payments_merge(monkeypatch, result=None, error=None) -> list:
    calls = []

    def fake_merge_payments(from_member_id, to_member_id):
        calls.append((from_member_id, to_member_id))
        if error is not None:
            raise error
        return {"moved": 0} if result is None else result

    monkeypatch.setattr(payments_client, "merge_payments", fake_merge_payments)
    return calls


@pytest.mark.parametrize(
    "duplicate_member_id",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param("1", id="string"),
        pytest.param(True, id="boolean"),
        pytest.param(None, id="null"),
    ],
)
def test_merge_rejects_invalid_duplicate_id_before_any_lookup(
    client, monkeypatch, duplicate_member_id
):
    calls = stub_payments_merge(monkeypatch)

    response = client.post(
        "/api/members/merge",
        json={
            "keptMemberId": 999999,
            "duplicateMemberId": duplicate_member_id,
        },
    )

    assert response.status_code == 400
    assert "duplicateMemberId" in response.get_json()["message"]
    assert calls == []


def test_merge_rejects_a_missing_duplicate_id_before_any_lookup(client, monkeypatch):
    calls = stub_payments_merge(monkeypatch)

    response = client.post("/api/members/merge", json={"keptMemberId": 999999})

    assert response.status_code == 400
    assert "duplicateMemberId" in response.get_json()["message"]
    assert calls == []


@pytest.mark.parametrize(
    "kept_member_id",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param("1", id="string"),
        pytest.param(True, id="boolean"),
    ],
)
def test_merge_rejects_invalid_kept_id(client, monkeypatch, kept_member_id):
    calls = stub_payments_merge(monkeypatch)
    duplicate = create_member(client).get_json()

    response = client.post(
        "/api/members/merge",
        json={"keptMemberId": kept_member_id, "duplicateMemberId": duplicate["id"]},
    )

    assert response.status_code == 400
    assert "keptMemberId" in response.get_json()["message"]
    assert calls == []


def test_merge_returns_404_for_missing_kept_member(client, monkeypatch):
    calls = stub_payments_merge(monkeypatch)
    duplicate = create_member(client).get_json()

    response = client.post(
        "/api/members/merge",
        json={"keptMemberId": 999999, "duplicateMemberId": duplicate["id"]},
    )

    assert response.status_code == 404
    assert "not found" in response.get_json()["message"]
    assert calls == []


def test_merge_returns_404_for_missing_duplicate_member(client, monkeypatch):
    calls = stub_payments_merge(monkeypatch)
    kept = create_member(client).get_json()

    response = client.post(
        "/api/members/merge",
        json={"keptMemberId": kept["id"], "duplicateMemberId": 999999},
    )

    assert response.status_code == 404
    assert "duplicateMemberId" in response.get_json()["message"]
    assert calls == []


def test_merge_rejects_self_merge(client, monkeypatch):
    calls = stub_payments_merge(monkeypatch)
    kept = create_member(client).get_json()

    response = client.post(
        "/api/members/merge",
        json={"keptMemberId": kept["id"], "duplicateMemberId": kept["id"]},
    )

    assert response.status_code == 400
    assert "must be different" in response.get_json()["message"]
    assert calls == []


def test_merge_returns_kept_member_unchanged_and_deletes_duplicate(client, monkeypatch):
    calls = stub_payments_merge(monkeypatch, result={"moved": 2})
    kept = create_member(client).get_json()
    duplicate = create_member(client, email="duplicate@example.com").get_json()

    response = client.post(
        "/api/members/merge",
        json={"keptMemberId": kept["id"], "duplicateMemberId": duplicate["id"]},
    )

    assert response.status_code == 200
    assert response.get_json() == kept
    assert client.get(f"/api/members/{kept['id']}").get_json() == kept
    assert client.get(f"/api/members/{duplicate['id']}").status_code == 404
    assert calls == [(duplicate["id"], kept["id"])]


def test_merge_returns_502_and_leaves_both_accounts_when_payments_fail(client, monkeypatch):
    stub_payments_merge(
        monkeypatch, error=ApiError(502, "payments service unavailable")
    )
    kept = create_member(client).get_json()
    duplicate = create_member(client, email="duplicate@example.com").get_json()

    response = client.post(
        "/api/members/merge",
        json={"keptMemberId": kept["id"], "duplicateMemberId": duplicate["id"]},
    )

    assert response.status_code == 502
    assert response.get_json()["message"] == "payments service unavailable"
    assert client.get(f"/api/members/{kept['id']}").get_json() == kept
    assert client.get(f"/api/members/{duplicate['id']}").status_code == 200


def test_merge_retry_after_failed_local_delete_completes_without_moving_payments_twice(
    client, monkeypatch
):
    kept = create_member(client).get_json()
    duplicate = create_member(client, email="duplicate@example.com").get_json()

    calls = []
    answers = []

    def fake_merge_payments(from_member_id, to_member_id):
        calls.append((from_member_id, to_member_id))
        moved = 2 if len(calls) == 1 else 0
        answers.append(moved)
        return {"moved": moved}

    monkeypatch.setattr(payments_client, "merge_payments", fake_merge_payments)

    session_type = type(db.session)
    real_commit = session_type.commit
    failures = [1]

    def flaky_commit(self):
        if failures[0]:
            failures[0] -= 1
            raise RuntimeError("database is locked")
        return real_commit(self)

    monkeypatch.setattr(session_type, "commit", flaky_commit)

    payload = {"keptMemberId": kept["id"], "duplicateMemberId": duplicate["id"]}

    first = client.post("/api/members/merge", json=payload)

    assert first.status_code == 500
    assert first.get_json()["message"] == "failed to merge members"
    assert client.get(f"/api/members/{kept['id']}").status_code == 200
    assert client.get(f"/api/members/{duplicate['id']}").status_code == 200
    assert calls == [(duplicate["id"], kept["id"])]

    second = client.post("/api/members/merge", json=payload)

    assert second.status_code == 200
    assert second.get_json() == kept
    assert client.get(f"/api/members/{duplicate['id']}").status_code == 404
    assert calls == [(duplicate["id"], kept["id"])] * 2
    assert answers == [2, 0]


def test_unknown_route_returns_404(client):
    response = client.get("/api/not-a-real-route")

    assert response.status_code == 404
    assert "message" in response.get_json()
