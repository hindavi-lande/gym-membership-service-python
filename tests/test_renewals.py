from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from flask import Response

from app.clients import payments_client
from app.clients.payments_client import (
    CALL_TIMEOUT_SECONDS,
    ChargeResult,
    PaymentsUnavailable,
    post_charge,
)
from app.extensions import db
from app.models import Member

PAYMENTS_BASE_URL = "http://localhost:3001"
RENEWAL_PERIOD = timedelta(days=30)

valid_member = {
    "firstName": "Jane",
    "lastName": "Doe",
    "email": "jane@example.com",
    "membershipPlan": "STANDARD",
}


class PaymentsStub(list):
    """Call log for the stubbed payments client, with a configurable response."""

    def __init__(self) -> None:
        super().__init__()
        self.result = ChargeResult(status_code=201, body={"id": 1, "status": "SUCCESS"})
        self.error: Exception | None = None


@pytest.fixture()
def stub_payments(monkeypatch) -> PaymentsStub:
    stub = PaymentsStub()

    def fake_post_charge(
        base_url: str,
        payload: dict,
        timeout: float = CALL_TIMEOUT_SECONDS,
    ) -> ChargeResult:
        stub.append({"base_url": base_url, "payload": payload})
        if stub.error is not None:
            raise stub.error
        return stub.result

    monkeypatch.setattr(payments_client, "post_charge", fake_post_charge)
    return stub


def create_member(client, **overrides):
    payload = {**valid_member, **overrides}
    return client.post("/api/members", json=payload)


def renew(client, member_id: int) -> Response:
    return client.post(f"/api/members/{member_id}/renew")


def renewal_date_of(client, member_id: int):
    return client.get(f"/api/members/{member_id}").get_json()["renewalDate"]


def set_renewal_date(member_id: int, renewal_date: date) -> None:
    member = db.session.get(Member, member_id)
    member.renewal_date = renewal_date
    db.session.commit()


def expected_renewal_date() -> date:
    return datetime.now(UTC).date() + RENEWAL_PERIOD


@pytest.mark.parametrize(
    ("plan", "amount"),
    [("BASIC", 29.99), ("STANDARD", 49.99), ("PREMIUM", 79.99)],
)
def test_renew_charges_the_current_plan_price(client, stub_payments, plan, amount):
    created = create_member(client, membershipPlan=plan).get_json()

    response = renew(client, created["id"])

    assert response.status_code == 200
    assert stub_payments == [
        {
            "base_url": PAYMENTS_BASE_URL,
            "payload": {
                "memberId": created["id"],
                "amount": amount,
                "reason": f"{plan} plan renewal",
            },
        }
    ]


def test_renew_sets_the_renewal_date_thirty_days_ahead(client, stub_payments):
    created = create_member(client).get_json()
    expected = expected_renewal_date()

    response = renew(client, created["id"])

    assert response.status_code == 200
    assert response.get_json()["renewalDate"] == expected.isoformat()

    db.session.expire_all()
    assert db.session.get(Member, created["id"]).renewal_date == expected


def test_renew_persists_the_renewal_date_for_later_reads(client, stub_payments):
    created = create_member(client).get_json()
    expected = expected_renewal_date()

    renew(client, created["id"])

    assert renewal_date_of(client, created["id"]) == expected.isoformat()
    listed = client.get("/api/members").get_json()
    assert listed[0]["renewalDate"] == expected.isoformat()


def test_renew_returns_402_and_keeps_an_existing_renewal_date(client, stub_payments):
    created = create_member(client).get_json()
    set_renewal_date(created["id"], date(2024, 1, 31))
    stub_payments.result = ChargeResult(status_code=402, body={"message": "declined"})

    response = renew(client, created["id"])

    assert response.status_code == 402
    assert renewal_date_of(client, created["id"]) == "2024-01-31"


def test_renew_returns_402_and_leaves_no_renewal_when_none_existed(client, stub_payments):
    created = create_member(client).get_json()
    stub_payments.result = ChargeResult(status_code=402, body={"message": "declined"})

    response = renew(client, created["id"])

    assert response.status_code == 402
    assert renewal_date_of(client, created["id"]) is None


def test_renew_returns_502_for_an_unexpected_payments_response(client, stub_payments):
    created = create_member(client).get_json()
    stub_payments.result = ChargeResult(status_code=500, body={"message": "boom"})

    response = renew(client, created["id"])

    assert response.status_code == 502
    assert renewal_date_of(client, created["id"]) is None


def test_renew_returns_503_when_the_payments_service_is_unreachable(client, stub_payments):
    created = create_member(client).get_json()
    set_renewal_date(created["id"], date(2024, 1, 31))
    stub_payments.error = PaymentsUnavailable("connection refused")

    response = renew(client, created["id"])

    assert response.status_code == 503
    assert renewal_date_of(client, created["id"]) == "2024-01-31"


def test_renew_returns_404_and_makes_no_charge_for_an_unknown_member(client, stub_payments):
    response = renew(client, 999999)

    assert response.status_code == 404
    assert stub_payments == []


@pytest.mark.parametrize("status", ["INACTIVE", "SUSPENDED"])
def test_renew_returns_409_and_makes_no_charge_for_an_inactive_member(
    client, stub_payments, status
):
    created = create_member(client, status=status).get_json()
    set_renewal_date(created["id"], date(2024, 1, 31))

    response = renew(client, created["id"])

    assert response.status_code == 409
    assert stub_payments == []
    assert renewal_date_of(client, created["id"]) == "2024-01-31"


def test_member_responses_carry_renewal_date(client):
    created = create_member(client).get_json()

    detail = client.get(f"/api/members/{created['id']}").get_json()
    listed = client.get("/api/members").get_json()

    assert created["renewalDate"] is None
    assert detail["renewalDate"] is None
    assert listed[0]["renewalDate"] is None


def test_post_charge_posts_the_payload_to_the_charge_endpoint(monkeypatch):
    calls = []

    def fake_post(url, *, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return httpx.Response(201, json={"id": 7, "status": "SUCCESS"})

    monkeypatch.setattr(httpx, "post", fake_post)

    result = post_charge(PAYMENTS_BASE_URL, {"memberId": 1, "amount": 29.99})

    assert calls == [
        {
            "url": f"{PAYMENTS_BASE_URL}/api/payments/charge",
            "json": {"memberId": 1, "amount": 29.99},
            "timeout": CALL_TIMEOUT_SECONDS,
        }
    ]
    assert result == ChargeResult(status_code=201, body={"id": 7, "status": "SUCCESS"})


def test_post_charge_wraps_transport_errors(monkeypatch):
    def fake_post(url, *, json, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(PaymentsUnavailable):
        post_charge(PAYMENTS_BASE_URL, {"memberId": 1})
