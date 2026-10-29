import io
import urllib.error
import urllib.request

from app.errors import ApiError
from app.extensions import db

DEFAULT_MEMBER = {
    "firstName": "Jane",
    "lastName": "Doe",
    "email": "jane@example.com",
    "membershipPlan": "PREMIUM",
}


def create_member(client, **overrides):
    payload = {**DEFAULT_MEMBER, **overrides}
    return client.post("/api/members", json=payload)


def create_pair(client):
    kept = create_member(client, email="kept@example.com").get_json()
    duplicate = create_member(client, email="duplicate@example.com").get_json()
    return kept, duplicate


def install_fake_payments(monkeypatch, moved=1, error=None):
    calls = []
    moved_pairs = set()

    def fake_merge_payments(from_member_id, to_member_id, *args, **kwargs):
        calls.append((from_member_id, to_member_id))
        if error is not None:
            raise error
        pair = (from_member_id, to_member_id)
        if pair in moved_pairs:
            return {"moved": 0}
        moved_pairs.add(pair)
        return {"moved": moved}

    monkeypatch.setattr("app.clients.payments.merge_payments", fake_merge_payments)
    return calls


def _install_failing_urlopen(monkeypatch, error):
    def fake_urlopen(request, timeout=None):
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_merge_validates_duplicate_member_id_before_looking_up_members(client, monkeypatch):
    calls = install_fake_payments(monkeypatch)

    for payload in (
        {},
        {"duplicateMemberId": None},
        {"duplicateMemberId": "2"},
        {"duplicateMemberId": 0},
        {"duplicateMemberId": -1},
        {"duplicateMemberId": 1.5},
        {"duplicateMemberId": True},
    ):
        response = client.post("/api/members/999999/merge", json=payload)

        assert response.status_code == 400
        assert "duplicateMemberId" in response.get_json()["message"]

    not_an_object = client.post("/api/members/999999/merge", json=[1, 2])
    assert not_an_object.status_code == 400
    assert not_an_object.get_json()["message"] == "Request body must be a JSON object"

    # A valid duplicateMemberId is what lets the lookup happen, and only then is 404 returned.
    response = client.post("/api/members/999999/merge", json={"duplicateMemberId": 1})

    assert response.status_code == 404
    assert "999999" in response.get_json()["message"]
    assert calls == []


def test_merge_returns_404_for_missing_members_without_calling_payments(client, monkeypatch):
    calls = install_fake_payments(monkeypatch)
    existing = create_member(client).get_json()

    unknown_kept = client.post(
        "/api/members/999999/merge", json={"duplicateMemberId": existing["id"]}
    )
    assert unknown_kept.status_code == 404
    assert "999999" in unknown_kept.get_json()["message"]

    unknown_duplicate = client.post(
        f"/api/members/{existing['id']}/merge", json={"duplicateMemberId": 999999}
    )
    assert unknown_duplicate.status_code == 404
    assert "999999" in unknown_duplicate.get_json()["message"]

    assert calls == []
    assert client.get(f"/api/members/{existing['id']}").status_code == 200


def test_merge_rejects_self_merge(client, monkeypatch):
    calls = install_fake_payments(monkeypatch)
    member = create_member(client).get_json()
    before = client.get(f"/api/members/{member['id']}").get_json()

    response = client.post(
        f"/api/members/{member['id']}/merge",
        json={"duplicateMemberId": member["id"]},
    )

    assert response.status_code == 400
    assert "duplicateMemberId" in response.get_json()["message"]
    assert calls == []
    assert client.get(f"/api/members/{member['id']}").get_json() == before


def test_merge_deletes_duplicate_and_returns_unchanged_kept_member(client, monkeypatch):
    kept, duplicate = create_pair(client)
    kept_before = client.get(f"/api/members/{kept['id']}").get_json()
    calls = install_fake_payments(monkeypatch, moved=2)

    response = client.post(
        f"/api/members/{kept['id']}/merge",
        json={"duplicateMemberId": duplicate["id"]},
    )

    assert response.status_code == 200
    assert response.get_json() == kept_before
    assert client.get(f"/api/members/{duplicate['id']}").status_code == 404
    assert client.get(f"/api/members/{kept['id']}").get_json() == kept_before
    assert calls == [(duplicate["id"], kept["id"])]


def test_merge_returns_502_and_keeps_both_accounts_when_payments_fail(client, monkeypatch):
    kept, duplicate = create_pair(client)
    kept_before = client.get(f"/api/members/{kept['id']}").get_json()
    duplicate_before = client.get(f"/api/members/{duplicate['id']}").get_json()
    calls = install_fake_payments(
        monkeypatch, error=ApiError(502, "Payments service is unreachable")
    )

    response = client.post(
        f"/api/members/{kept['id']}/merge",
        json={"duplicateMemberId": duplicate["id"]},
    )

    assert response.status_code == 502
    assert response.get_json()["message"] == "Payments service is unreachable"
    assert calls == [(duplicate["id"], kept["id"])]
    assert client.get(f"/api/members/{kept['id']}").get_json() == kept_before
    assert client.get(f"/api/members/{duplicate['id']}").get_json() == duplicate_before


def test_merge_returns_502_when_payments_service_is_unreachable(client, monkeypatch):
    kept, duplicate = create_pair(client)
    kept_before = client.get(f"/api/members/{kept['id']}").get_json()
    duplicate_before = client.get(f"/api/members/{duplicate['id']}").get_json()
    _install_failing_urlopen(monkeypatch, urllib.error.URLError("connection refused"))

    response = client.post(
        f"/api/members/{kept['id']}/merge",
        json={"duplicateMemberId": duplicate["id"]},
    )

    assert response.status_code == 502
    assert response.get_json()["message"] == "Payments service is unreachable"
    assert client.get(f"/api/members/{kept['id']}").get_json() == kept_before
    assert client.get(f"/api/members/{duplicate['id']}").get_json() == duplicate_before


def test_merge_returns_502_when_payments_service_returns_500(client, monkeypatch):
    kept, duplicate = create_pair(client)
    kept_before = client.get(f"/api/members/{kept['id']}").get_json()
    duplicate_before = client.get(f"/api/members/{duplicate['id']}").get_json()
    _install_failing_urlopen(
        monkeypatch,
        urllib.error.HTTPError(
            "http://localhost:3001/api/payments/merge",
            500,
            "Internal Server Error",
            None,
            io.BytesIO(b"{}"),
        ),
    )

    response = client.post(
        f"/api/members/{kept['id']}/merge",
        json={"duplicateMemberId": duplicate["id"]},
    )

    assert response.status_code == 502
    assert "500" in response.get_json()["message"]
    assert client.get(f"/api/members/{kept['id']}").get_json() == kept_before
    assert client.get(f"/api/members/{duplicate['id']}").get_json() == duplicate_before


def test_retry_after_failed_local_delete_completes_the_merge(client, monkeypatch):
    """A failed local delete must be retryable: the payments move only happens once.

    The fake below stands in for the real (idempotent) payments endpoint, so "payments were
    moved only once" is asserted across this file and the payments service's own merge tests
    together, not inside this file alone.
    """
    kept, duplicate = create_pair(client)
    kept_before = client.get(f"/api/members/{kept['id']}").get_json()

    calls = []
    responses = []
    moved_pairs = set()

    def fake_merge_payments(from_member_id, to_member_id, *args, **kwargs):
        pair = (from_member_id, to_member_id)
        calls.append(pair)
        result = {"moved": 0} if pair in moved_pairs else {"moved": 2}
        moved_pairs.add(pair)
        responses.append(result)
        return result

    monkeypatch.setattr("app.clients.payments.merge_payments", fake_merge_payments)

    real_commit = db.session.commit
    attempts = {"commits": 0}

    def flaky_commit(*args, **kwargs):
        attempts["commits"] += 1
        if attempts["commits"] == 1:
            raise RuntimeError("local delete failed")
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(db.session, "commit", flaky_commit)

    first = client.post(
        f"/api/members/{kept['id']}/merge",
        json={"duplicateMemberId": duplicate["id"]},
    )

    assert first.status_code == 500
    assert calls == [(duplicate["id"], kept["id"])]
    assert responses == [{"moved": 2}]

    # Flask-SQLAlchemy's session teardown discards the failed unit of work; do the same here
    # so the duplicate row provably survives the failed attempt.
    db.session.rollback()
    assert client.get(f"/api/members/{duplicate['id']}").status_code == 200
    assert client.get(f"/api/members/{kept['id']}").get_json() == kept_before

    second = client.post(
        f"/api/members/{kept['id']}/merge",
        json={"duplicateMemberId": duplicate["id"]},
    )

    assert second.status_code == 200
    assert second.get_json() == kept_before
    assert client.get(f"/api/members/{duplicate['id']}").status_code == 404
    assert client.get(f"/api/members/{kept['id']}").get_json() == kept_before
    assert calls == [(duplicate["id"], kept["id"]), (duplicate["id"], kept["id"])]
    assert responses[1] == {"moved": 0}
