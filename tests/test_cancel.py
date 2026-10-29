from datetime import UTC, datetime, timedelta

import pytest

from app.clients import payments_client
from app.errors import ApiError
from app.extensions import db
from app.models import Member

valid_member = {
    "firstName": "Jane",
    "lastName": "Doe",
    "email": "jane@example.com",
    "membershipPlan": "PREMIUM",
}

RESPONSE_KEYS = {"status", "amount", "paymentId", "refundFollowUpRequired", "message"}

SUCCESSFUL_CHARGE = {"id": 42, "type": "CHARGE", "status": "SUCCESS", "amount": "79.99"}


def create_member(client, **overrides):
    payload = {**valid_member, **overrides}
    return client.post("/api/members", json=payload)


def cancel_member(client, member_id):
    return client.post(f"/api/members/{member_id}/cancel")


def fetch_member(client, member_id):
    return client.get(f"/api/members/{member_id}").get_json()


def set_renewal_date(member_id, renewal_date):
    member = db.session.get(Member, member_id)
    member.renewal_date = renewal_date
    db.session.commit()


def in_days(days):
    return datetime.now(UTC).date() + timedelta(days=days)


class RecordedRefunds(list):
    """Refunds sent to the payments service, plus a way to script the answer."""

    def __init__(self):
        super().__init__()
        self.error = None
        self.response = None

    def fail_with(self, error):
        self.error = error

    def respond_with(self, response):
        self.response = response


@pytest.fixture()
def recorded_refunds(monkeypatch):
    refunds = RecordedRefunds()

    def fake_refund(payload):
        refunds.append(payload)
        if refunds.error is not None:
            raise refunds.error
        if refunds.response is not None:
            return refunds.response
        return {"id": 7, "status": "SUCCESS", "amount": payload["amount"]}

    monkeypatch.setattr(payments_client, "refund", fake_refund)
    return refunds


class RecordedHistory(list):
    """Member ids looked up in the payments history, plus its scripted answer."""

    def __init__(self):
        super().__init__()
        self.error = None
        self.entries = []

    def fail_with(self, error):
        self.error = error

    def respond_with(self, entries):
        self.entries = entries


@pytest.fixture()
def recorded_history(monkeypatch):
    lookups = RecordedHistory()

    def fake_history(member_id):
        lookups.append(member_id)
        if lookups.error is not None:
            raise lookups.error
        return list(lookups.entries)

    monkeypatch.setattr(payments_client, "history", fake_history)
    return lookups


def test_cancel_refunds_unused_days_and_sets_inactive(
    client, recorded_refunds, recorded_history
):
    created = create_member(client).get_json()
    set_renewal_date(created["id"], in_days(10))
    recorded_history.respond_with(
        [
            {"id": 11, "type": "REFUND", "status": "SUCCESS", "amount": "5.00"},
            {"id": 12, "type": "CHARGE", "status": "FAILED", "amount": "79.99"},
            SUCCESSFUL_CHARGE,
        ]
    )

    response = cancel_member(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == RESPONSE_KEYS
    assert body["status"] == "SUCCESS"
    assert body["amount"] == 26.66
    assert body["paymentId"] == 7
    assert body["refundFollowUpRequired"] is False
    assert len(recorded_refunds) == 1
    assert recorded_refunds[0]["memberId"] == created["id"]
    assert recorded_refunds[0]["amount"] == 26.66
    assert recorded_refunds[0]["relatedPaymentId"] == 42
    assert recorded_refunds[0]["reason"] == "PREMIUM plan cancellation refund"
    assert fetch_member(client, created["id"])["status"] == "INACTIVE"


def test_cancel_rounds_the_refund_half_up(client, recorded_refunds, recorded_history):
    created = create_member(client, membershipPlan="BASIC").get_json()
    set_renewal_date(created["id"], in_days(15))
    recorded_history.respond_with([{**SUCCESSFUL_CHARGE, "amount": "29.99"}])

    response = cancel_member(client, created["id"])

    assert response.status_code == 200
    # 29.99 * 15 / 30 = 14.995, which rounds half-up to 15.00.
    assert recorded_refunds[0]["amount"] == 15.00
    assert response.get_json()["amount"] == 15.00


def test_cancel_caps_the_refund_at_the_linked_charge_amount(
    client, recorded_refunds, recorded_history
):
    created = create_member(client).get_json()
    set_renewal_date(created["id"], in_days(30))
    recorded_history.respond_with([{**SUCCESSFUL_CHARGE, "amount": "20.00"}])

    response = cancel_member(client, created["id"])

    assert response.status_code == 200
    assert recorded_refunds[0]["amount"] == 20.00
    assert response.get_json()["amount"] == 20.00


def test_cancel_reports_a_pending_refund_without_follow_up(
    client, recorded_refunds, recorded_history
):
    created = create_member(client).get_json()
    set_renewal_date(created["id"], in_days(10))
    recorded_history.respond_with([SUCCESSFUL_CHARGE])
    recorded_refunds.respond_with({"id": 9, "status": "PENDING", "amount": 26.66})

    response = cancel_member(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "PENDING"
    assert body["paymentId"] == 9
    assert body["amount"] == 26.66
    assert body["refundFollowUpRequired"] is False
    assert fetch_member(client, created["id"])["status"] == "INACTIVE"


def test_cancel_refund_failure_keeps_member_inactive_and_requires_follow_up(
    client, recorded_refunds, recorded_history
):
    created = create_member(client).get_json()
    set_renewal_date(created["id"], in_days(10))
    recorded_history.respond_with([SUCCESSFUL_CHARGE])
    recorded_refunds.fail_with(ApiError(503, "payments service unavailable"))

    response = cancel_member(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "FAILED"
    assert body["refundFollowUpRequired"] is True
    assert body["amount"] == 26.66
    assert body["paymentId"] is None
    assert "follow-up" in body["message"]
    assert fetch_member(client, created["id"])["status"] == "INACTIVE"


def test_cancel_when_the_payment_history_is_unavailable_requires_follow_up(
    client, recorded_refunds, recorded_history
):
    created = create_member(client).get_json()
    set_renewal_date(created["id"], in_days(10))
    recorded_history.fail_with(ApiError(503, "payments service unavailable"))

    response = cancel_member(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "FAILED"
    assert body["refundFollowUpRequired"] is True
    assert "follow-up" in body["message"]
    assert recorded_refunds == []
    assert fetch_member(client, created["id"])["status"] == "INACTIVE"


@pytest.mark.parametrize("days_out", [0, -1, -10])
def test_cancel_with_a_renewal_date_today_or_past_is_not_eligible(
    client, recorded_refunds, recorded_history, days_out
):
    created = create_member(client).get_json()
    set_renewal_date(created["id"], in_days(days_out))

    response = cancel_member(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "NOT_ELIGIBLE"
    assert body["amount"] is None
    assert body["paymentId"] is None
    assert body["refundFollowUpRequired"] is False
    assert recorded_refunds == []
    assert fetch_member(client, created["id"])["status"] == "INACTIVE"


@pytest.mark.parametrize(
    ("renewal_days_out", "history_entries"),
    [
        (None, []),
        (10, [{"id": 12, "type": "CHARGE", "status": "FAILED", "amount": "79.99"}]),
    ],
)
def test_cancel_without_a_paid_period_is_not_eligible(
    client, recorded_refunds, recorded_history, renewal_days_out, history_entries
):
    created = create_member(client).get_json()
    if renewal_days_out is not None:
        set_renewal_date(created["id"], in_days(renewal_days_out))
    recorded_history.respond_with(history_entries)

    response = cancel_member(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "NOT_ELIGIBLE"
    assert body["amount"] is None
    assert body["paymentId"] is None
    assert body["refundFollowUpRequired"] is False
    assert recorded_refunds == []
    assert fetch_member(client, created["id"])["status"] == "INACTIVE"


def test_cancel_of_an_inactive_member_is_not_eligible_and_calls_no_payments(
    client, recorded_refunds, recorded_history
):
    created = create_member(client).get_json()
    client.put(f"/api/members/{created['id']}", json={"status": "INACTIVE"})
    set_renewal_date(created["id"], in_days(10))

    response = cancel_member(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "NOT_ELIGIBLE"
    assert body["refundFollowUpRequired"] is False
    assert recorded_refunds == []
    assert recorded_history == []


def test_cancel_unknown_member_returns_404_and_calls_no_payments(
    client, recorded_refunds, recorded_history
):
    response = cancel_member(client, 999999)

    assert response.status_code == 404
    assert recorded_refunds == []
    assert recorded_history == []


def test_cancel_is_idempotent(client, recorded_refunds, recorded_history):
    created = create_member(client).get_json()
    set_renewal_date(created["id"], in_days(10))
    recorded_history.respond_with([SUCCESSFUL_CHARGE])

    first = cancel_member(client, created["id"])
    second = cancel_member(client, created["id"])

    assert first.status_code == 200
    assert first.get_json()["status"] == "SUCCESS"
    assert second.status_code == 200
    assert second.get_json()["status"] == "NOT_ELIGIBLE"
    assert len(recorded_refunds) == 1
    assert fetch_member(client, created["id"])["status"] == "INACTIVE"
