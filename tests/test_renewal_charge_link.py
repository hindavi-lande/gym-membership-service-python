import pytest
from flask import Response

from app.clients import payments_client
from app.clients.payments_client import (
    CALL_TIMEOUT_SECONDS,
    ChargeResult,
    PaymentsUnavailable,
)
from app.extensions import db
from app.models import Member

PAYMENTS_BASE_URL = "http://localhost:3001"

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
def stub_payments(monkeypatch) -> list[dict]:
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


def create_member(client, **overrides) -> Response:
    payload = {**valid_member, **overrides}
    return client.post("/api/members", json=payload)


def renew(client, member_id: int) -> Response:
    return client.post(f"/api/members/{member_id}/renew")


def stored_last_charge_payment_id(member_id: int) -> int | None:
    db.session.expire_all()
    return db.session.get(Member, member_id).last_charge_payment_id


def test_renew_records_the_charge_id_on_the_member(client, stub_payments) -> None:
    stub_payments.result = ChargeResult(
        status_code=201, body={"id": 42, "status": "SUCCESS"}
    )
    created = create_member(client).get_json()

    response = renew(client, created["id"])

    assert response.status_code == 200
    assert stub_payments == [
        {
            "base_url": PAYMENTS_BASE_URL,
            "payload": {
                "memberId": created["id"],
                "amount": 49.99,
                "reason": "STANDARD plan renewal",
            },
        }
    ]

    detail = client.get(f"/api/members/{created['id']}").get_json()
    assert detail["lastChargePaymentId"] == 42
    assert stored_last_charge_payment_id(created["id"]) == 42


def test_last_charge_payment_id_is_null_before_any_renewal(client) -> None:
    created = create_member(client).get_json()

    detail = client.get(f"/api/members/{created['id']}").get_json()
    listed = client.get("/api/members").get_json()

    assert created["lastChargePaymentId"] is None
    assert detail["lastChargePaymentId"] is None
    assert listed[0]["lastChargePaymentId"] is None


@pytest.mark.parametrize(
    ("result", "error", "expected_status"),
    [
        (ChargeResult(status_code=402, body={"message": "declined"}), None, 402),
        (ChargeResult(status_code=500, body={"message": "boom"}), None, 502),
        (None, PaymentsUnavailable("connection refused"), 503),
    ],
)
def test_failed_renewal_leaves_last_charge_payment_id_unchanged(
    client, stub_payments, result, error, expected_status
) -> None:
    created = create_member(client).get_json()
    if error is not None:
        stub_payments.error = error
    else:
        stub_payments.result = result

    response = renew(client, created["id"])

    assert response.status_code == expected_status
    detail = client.get(f"/api/members/{created['id']}").get_json()
    assert detail["lastChargePaymentId"] is None
    assert stored_last_charge_payment_id(created["id"]) is None
