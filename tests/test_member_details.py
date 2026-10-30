from datetime import UTC, datetime, timedelta

import pytest

from app.clients import payments_client
from app.clients.payments_client import (
    CALL_TIMEOUT_SECONDS,
    ChargeResult,
    PaymentHistoryResult,
    PaymentsUnavailable,
)

PAYMENTS_BASE_URL = "http://localhost:3001"
RENEWAL_PERIOD = timedelta(days=30)

valid_member = {
    "firstName": "Jane",
    "lastName": "Doe",
    "email": "jane@example.com",
    "membershipPlan": "STANDARD",
}


class PaymentHistoryStub(list):
    """Call log for the stubbed payment history client, with a configurable response."""

    def __init__(self) -> None:
        super().__init__()
        self.result = PaymentHistoryResult(status_code=200, payments=[])
        self.error: Exception | None = None


@pytest.fixture()
def stub_payment_history(monkeypatch) -> PaymentHistoryStub:
    stub = PaymentHistoryStub()

    def fake_get_payment_history(
        base_url: str,
        member_id: int,
        timeout: float = CALL_TIMEOUT_SECONDS,
    ) -> PaymentHistoryResult:
        stub.append({"base_url": base_url, "member_id": member_id, "timeout": timeout})
        if stub.error is not None:
            raise stub.error
        return stub.result

    monkeypatch.setattr(payments_client, "get_payment_history", fake_get_payment_history)
    return stub


@pytest.fixture()
def stub_charge(monkeypatch) -> list:
    calls = []

    def fake_post_charge(
        base_url: str,
        payload: dict,
        timeout: float = CALL_TIMEOUT_SECONDS,
    ) -> ChargeResult:
        calls.append({"base_url": base_url, "payload": payload})
        return ChargeResult(status_code=201, body={"id": 1, "status": "SUCCESS"})

    monkeypatch.setattr(payments_client, "post_charge", fake_post_charge)
    return calls


def create_member(client, **overrides):
    payload = {**valid_member, **overrides}
    return client.post("/api/members", json=payload)


def details(client, member_id: int):
    return client.get(f"/api/members/{member_id}/details")


def payment_row(payment_id, created_at, **overrides):
    row = {
        "id": payment_id,
        "memberId": 1,
        "type": "CHARGE",
        "status": "SUCCESS",
        "amount": "49.99",
        "refundedAmount": 0,
        "createdAt": created_at,
    }
    row.update(overrides)
    return row


def test_details_returns_exactly_member_and_payments(client, stub_payment_history):
    created = create_member(client).get_json()

    response = details(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"member", "payments"}
    assert body["member"]["id"] == created["id"]
    assert body["member"]["firstName"] == valid_member["firstName"]
    assert body["member"]["email"] == valid_member["email"]
    assert body["member"]["membershipPlan"] == "STANDARD"
    assert body["member"]["renewalDate"] is None
    assert body["payments"] == []
    assert stub_payment_history == [
        {
            "base_url": PAYMENTS_BASE_URL,
            "member_id": created["id"],
            "timeout": CALL_TIMEOUT_SECONDS,
        }
    ]


def test_details_member_carries_renewal_date_after_renewal(
    client, stub_payment_history, stub_charge
):
    created = create_member(client).get_json()

    before = details(client, created["id"]).get_json()
    assert before["member"]["renewalDate"] is None

    renewed = client.post(f"/api/members/{created['id']}/renew").get_json()
    expected = (datetime.now(UTC).date() + RENEWAL_PERIOD).isoformat()
    assert renewed["renewalDate"] == expected

    after = details(client, created["id"]).get_json()
    assert after["member"]["renewalDate"] == expected


def test_details_passes_refunded_amount_through_unchanged(client, stub_payment_history):
    created = create_member(client).get_json()
    rows = [
        payment_row(
            11,
            "2024-05-02T10:00:00.000Z",
            memberId=created["id"],
            refundedAmount=2000,
        ),
        payment_row(
            12,
            "2024-04-02T10:00:00.000Z",
            memberId=created["id"],
            type="REFUND",
            amount="20.00",
            refundedAmount=0,
        ),
    ]
    stub_payment_history.result = PaymentHistoryResult(status_code=200, payments=rows)

    response = details(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["payments"] == rows
    assert body["payments"][0]["refundedAmount"] == 2000
    assert body["payments"][1]["refundedAmount"] == 0


def test_details_orders_payments_most_recent_first_with_id_tiebreak(
    client, stub_payment_history
):
    created = create_member(client).get_json()
    oldest = payment_row(1, "2024-01-01T00:00:00.000Z")
    tied_low = payment_row(3, "2024-03-01T00:00:00.000Z")
    tied_high = payment_row(9, "2024-03-01T00:00:00.000Z")
    newest = payment_row(5, "2024-06-01T00:00:00.000Z")
    stub_payment_history.result = PaymentHistoryResult(
        status_code=200, payments=[oldest, tied_low, tied_high, newest]
    )

    response = details(client, created["id"])

    assert response.status_code == 200
    assert [row["id"] for row in response.get_json()["payments"]] == [5, 9, 3, 1]


def test_details_tolerates_malformed_rows_when_ordering(client, stub_payment_history):
    created = create_member(client).get_json()
    stub_payment_history.result = PaymentHistoryResult(
        status_code=200,
        payments=[
            payment_row(1, None),
            payment_row(2, "not-a-date"),
            {**payment_row(3, "2024-01-01T00:00:00.000Z"), "id": "three"},
            payment_row(4, "2024-04-01T00:00:00.000Z"),
            "not-a-row",
        ],
    )

    response = details(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert len(body["payments"]) == 4
    assert body["payments"][0]["id"] == 4


def test_details_falls_back_when_the_payments_service_is_unreachable(
    client, stub_payment_history
):
    created = create_member(client).get_json()
    stub_payment_history.error = PaymentsUnavailable("connection refused")

    response = details(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["member"]["id"] == created["id"]
    assert body["payments"] == []
    assert isinstance(body["paymentHistoryError"], str)
    assert body["paymentHistoryError"]


def test_details_falls_back_on_an_unexpected_payments_response(
    client, stub_payment_history
):
    created = create_member(client).get_json()
    stub_payment_history.result = PaymentHistoryResult(status_code=500, payments=[])

    response = details(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["member"]["id"] == created["id"]
    assert body["payments"] == []
    assert isinstance(body["paymentHistoryError"], str)
    assert body["paymentHistoryError"]


def test_details_returns_404_and_does_not_call_payments_for_an_unknown_member(
    client, stub_payment_history
):
    response = details(client, 999999)

    assert response.status_code == 404
    assert "message" in response.get_json()
    assert stub_payment_history == []


def test_details_with_empty_history_has_no_payment_history_error(
    client, stub_payment_history
):
    created = create_member(client).get_json()
    stub_payment_history.result = PaymentHistoryResult(status_code=200, payments=[])

    response = details(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["payments"] == []
    assert "paymentHistoryError" not in body
    assert set(body) == {"member", "payments"}
