from datetime import date, timedelta

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
RENEWED_PERIOD = timedelta(days=30)

valid_member = {
    "firstName": "Jane",
    "lastName": "Doe",
    "email": "jane@example.com",
    "membershipPlan": "STANDARD",
}


class PaymentsStub(list):
    """Call log for the stubbed payments client, with configurable responses."""

    def __init__(self) -> None:
        super().__init__()
        self.charge_result = ChargeResult(
            status_code=201, body={"id": 501, "status": "SUCCESS"}
        )
        self.refund_result = ChargeResult(
            status_code=201, body={"id": 900, "status": "SUCCESS"}
        )
        self.error: Exception | None = None

    def refund_calls(self) -> list[dict]:
        return [call for call in self if call["endpoint"] == "refund"]

    def refund_payloads(self) -> list[dict]:
        return [call["payload"] for call in self.refund_calls()]


@pytest.fixture()
def stub_payments(monkeypatch) -> PaymentsStub:
    stub = PaymentsStub()

    def fake_post_charge(
        base_url: str,
        payload: dict,
        timeout: float = CALL_TIMEOUT_SECONDS,
    ) -> ChargeResult:
        stub.append({"base_url": base_url, "payload": payload, "endpoint": "charge"})
        if stub.error is not None:
            raise stub.error
        return stub.charge_result

    def fake_post_refund(
        base_url: str,
        payload: dict,
        timeout: float = CALL_TIMEOUT_SECONDS,
    ) -> ChargeResult:
        stub.append({"base_url": base_url, "payload": payload, "endpoint": "refund"})
        if stub.error is not None:
            raise stub.error
        return stub.refund_result

    monkeypatch.setattr(payments_client, "post_charge", fake_post_charge)
    monkeypatch.setattr(payments_client, "post_refund", fake_post_refund)
    return stub


@pytest.fixture()
def renewed_member(client, stub_payments) -> tuple[dict, int]:
    created = create_member(client).get_json()
    renew(client, created["id"])
    set_renewal_date(created["id"], date.today() + RENEWED_PERIOD)
    return created, stub_payments.charge_result.body["id"]


def create_member(client, **overrides) -> Response:
    payload = {**valid_member, **overrides}
    return client.post("/api/members", json=payload)


def renew(client, member_id: int) -> Response:
    return client.post(f"/api/members/{member_id}/renew")


def cancel(client, member_id: int) -> Response:
    return client.post(f"/api/members/{member_id}/cancel")


def set_renewal_date(member_id: int, renewal_date: date | None) -> None:
    member = db.session.get(Member, member_id)
    member.renewal_date = renewal_date
    db.session.commit()


def member_detail(client, member_id: int) -> dict:
    return client.get(f"/api/members/{member_id}").get_json()


def test_cancel_refunds_price_times_remaining_days_over_30(
    client, stub_payments, renewed_member
) -> None:
    member, charge_id = renewed_member

    response = cancel(client, member["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["memberId"] == member["id"]
    assert body["memberStatus"] == "INACTIVE"
    assert body["status"] == "SUCCESS"
    assert body["amount"] == 49.99
    assert body["paymentId"] == stub_payments.refund_result.body["id"]
    assert body["refundFollowUpRequired"] is False

    refunds = stub_payments.refund_calls()
    assert len(refunds) == 1
    assert refunds[0]["base_url"] == PAYMENTS_BASE_URL
    payload = refunds[0]["payload"]
    assert payload["memberId"] == member["id"]
    assert payload["amount"] == 49.99
    assert payload["reason"] == "STANDARD plan cancellation refund"
    assert payload["relatedPaymentId"] == charge_id


@pytest.mark.parametrize(
    ("plan", "remaining_days", "expected"),
    [("STANDARD", 10, 16.66), ("BASIC", 15, 15.00)],
)
def test_cancel_rounds_the_refund_to_cents(
    client, stub_payments, plan, remaining_days, expected
) -> None:
    created = create_member(client, membershipPlan=plan).get_json()
    renew(client, created["id"])
    set_renewal_date(created["id"], date.today() + timedelta(days=remaining_days))

    response = cancel(client, created["id"])

    assert response.status_code == 200
    assert response.get_json()["amount"] == expected
    assert stub_payments.refund_payloads()[0]["amount"] == expected


def test_cancel_caps_the_refund_at_the_plan_price(client, stub_payments) -> None:
    created = create_member(client).get_json()
    renew(client, created["id"])
    set_renewal_date(created["id"], date.today() + timedelta(days=45))

    response = cancel(client, created["id"])

    assert response.status_code == 200
    assert response.get_json()["amount"] == 49.99
    assert stub_payments.refund_payloads()[0]["amount"] == 49.99


@pytest.mark.parametrize("days_ahead", [0, -1])
def test_cancel_returns_not_eligible_when_the_renewal_is_today_or_past(
    client, stub_payments, days_ahead
) -> None:
    created = create_member(client).get_json()
    renew(client, created["id"])
    set_renewal_date(created["id"], date.today() + timedelta(days=days_ahead))

    response = cancel(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "NOT_ELIGIBLE"
    assert body["amount"] == 0.0
    assert body["paymentId"] is None
    assert body["refundFollowUpRequired"] is False
    assert stub_payments.refund_calls() == []
    assert member_detail(client, created["id"])["status"] == "INACTIVE"


def test_cancel_without_a_paid_period_makes_no_refund(client, stub_payments) -> None:
    created = create_member(client).get_json()
    assert created["renewalDate"] is None

    response = cancel(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "NOT_ELIGIBLE"
    assert body["amount"] == 0.0
    assert body["paymentId"] is None
    assert stub_payments.refund_calls() == []
    assert member_detail(client, created["id"])["status"] == "INACTIVE"


def test_cancel_of_an_already_inactive_member_is_not_refunded_again(
    client, stub_payments, renewed_member
) -> None:
    member, _charge_id = renewed_member
    assert cancel(client, member["id"]).status_code == 200
    refunds_after_first_cancel = len(stub_payments.refund_calls())

    response = cancel(client, member["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "NOT_ELIGIBLE"
    assert body["amount"] == 0.0
    assert body["paymentId"] is None
    assert len(stub_payments.refund_calls()) == refunds_after_first_cancel
    assert member_detail(client, member["id"])["status"] == "INACTIVE"


def test_cancel_returns_404_and_makes_no_refund_for_an_unknown_member(
    client, stub_payments
) -> None:
    response = cancel(client, 999999)

    assert response.status_code == 404
    assert stub_payments == []


def test_cancel_reports_a_pending_refund_without_follow_up(
    client, stub_payments, renewed_member
) -> None:
    member, _charge_id = renewed_member
    stub_payments.refund_result = ChargeResult(
        status_code=201, body={"id": 902, "status": "PENDING"}
    )

    response = cancel(client, member["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "PENDING"
    assert body["refundFollowUpRequired"] is False
    assert body["paymentId"] == 902
    assert member_detail(client, member["id"])["status"] == "INACTIVE"


def test_cancel_reports_a_failed_refund_and_requires_follow_up(
    client, stub_payments, renewed_member
) -> None:
    member, _charge_id = renewed_member
    stub_payments.refund_result = ChargeResult(
        status_code=201, body={"id": 903, "status": "FAILED"}
    )

    response = cancel(client, member["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "FAILED"
    assert body["refundFollowUpRequired"] is True
    assert body["message"] == "Refund failed; follow-up required"
    assert body["paymentId"] == 903
    assert member_detail(client, member["id"])["status"] == "INACTIVE"


def test_cancel_rejects_a_refund_the_payments_service_refuses(
    client, stub_payments, renewed_member
) -> None:
    member, charge_id = renewed_member
    stub_payments.refund_result = ChargeResult(
        status_code=409, body={"message": "refund exceeds the charge amount"}
    )

    response = cancel(client, member["id"])

    assert response.status_code == 409
    detail = member_detail(client, member["id"])
    assert detail["status"] == "ACTIVE"
    assert detail["lastChargePaymentId"] == charge_id


@pytest.mark.parametrize(
    ("refund_result", "error", "expected_status"),
    [
        (None, PaymentsUnavailable("connection refused"), 503),
        (ChargeResult(status_code=500, body={"message": "boom"}), None, 502),
    ],
)
def test_cancel_maps_payments_outages(
    client, stub_payments, renewed_member, refund_result, error, expected_status
) -> None:
    member, _charge_id = renewed_member
    if error is not None:
        stub_payments.error = error
    else:
        stub_payments.refund_result = refund_result

    response = cancel(client, member["id"])

    assert response.status_code == expected_status
    assert member_detail(client, member["id"])["status"] == "ACTIVE"
