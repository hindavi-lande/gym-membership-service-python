from app.clients import payments_client
from app.errors import ApiError

valid_member = {
    "firstName": "Jane",
    "lastName": "Doe",
    "email": "jane@example.com",
    "membershipPlan": "PREMIUM",
}


def create_member(client, **overrides):
    payload = {**valid_member, **overrides}
    response = client.post("/api/members", json=payload)
    assert response.status_code == 201
    return response.get_json()


def stub_history(monkeypatch, history=None, error=None):
    calls = []

    def fake_history(member_id):
        calls.append(member_id)
        if error is not None:
            raise error
        return [] if history is None else history

    monkeypatch.setattr(payments_client, "history_for_member", fake_history)
    return calls


def make_payment(
    member_id,
    payment_id,
    payment_type,
    amount,
    *,
    status="SUCCESS",
    reason="Membership renewal",
    created_at="2024-01-01T00:00:00Z",
    related_payment_id=None,
):
    return {
        "id": payment_id,
        "memberId": member_id,
        "type": payment_type,
        "amount": amount,
        "status": status,
        "reason": reason,
        "relatedPaymentId": related_payment_id,
        "createdAt": created_at,
        "updatedAt": created_at,
    }


def test_returns_member_and_payments_only_on_success(client, monkeypatch):
    member = create_member(client)
    stub_history(monkeypatch, history=[make_payment(member["id"], 1, "CHARGE", 49.99)])

    response = client.get(f"/api/members/{member['id']}/payments")

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"member", "payments"}
    assert "paymentHistoryError" not in body
    assert body["member"]["id"] == member["id"]
    assert body["member"]["firstName"] == member["firstName"]
    assert body["member"]["lastName"] == member["lastName"]
    assert body["member"]["email"] == member["email"]
    assert body["member"]["membershipPlan"] == member["membershipPlan"]
    assert body["member"]["status"] == member["status"]
    assert "renewalDate" in body["member"]
    assert body["member"]["renewalDate"] == member["renewalDate"]
    assert len(body["payments"]) == 1


def test_charge_refunded_amount_sums_linked_refunds_of_any_status(client, monkeypatch):
    member = create_member(client)
    history = [
        make_payment(member["id"], 1, "CHARGE", 100.0),
        make_payment(
            member["id"],
            2,
            "REFUND",
            30.0,
            reason="Partial refund",
            related_payment_id=1,
        ),
        make_payment(
            member["id"],
            3,
            "REFUND",
            20.0,
            status="FAILED",
            reason="Second refund attempt",
            related_payment_id=1,
        ),
        make_payment(member["id"], 4, "CHARGE", 25.0),
        make_payment(member["id"], 5, "CHARGE", 40.0, status="FAILED"),
    ]
    stub_history(monkeypatch, history=history)

    response = client.get(f"/api/members/{member['id']}/payments")

    assert response.status_code == 200
    payments = response.get_json()["payments"]
    by_id = {payment["id"]: payment for payment in payments}
    assert set(by_id) == {1, 2, 3, 4, 5}

    assert by_id[1]["refundedAmount"] == 50.0
    assert by_id[4]["refundedAmount"] == 0
    assert by_id[5]["refundedAmount"] == 0

    for payment_id in (2, 3):
        assert "refundedAmount" not in by_id[payment_id]

    assert by_id[2]["type"] == "REFUND"
    assert by_id[2]["amount"] == 30.0
    assert by_id[2]["reason"] == "Partial refund"
    assert by_id[2]["status"] == "SUCCESS"
    assert by_id[2]["relatedPaymentId"] == 1

    assert by_id[3]["type"] == "REFUND"
    assert by_id[3]["amount"] == 20.0
    assert by_id[3]["reason"] == "Second refund attempt"
    assert by_id[3]["status"] == "FAILED"
    assert by_id[3]["relatedPaymentId"] == 1

    for payment in payments:
        assert payment["type"] in {"CHARGE", "REFUND"}
        assert "amount" in payment
        assert payment["createdAt"] is not None


def test_history_is_newest_first_with_id_tie_break(client, monkeypatch):
    member = create_member(client)
    history = [
        make_payment(member["id"], 1, "CHARGE", 10.0, created_at="2024-01-01T00:00:00Z"),
        make_payment(member["id"], 2, "CHARGE", 20.0, created_at="2024-03-01T00:00:00Z"),
        make_payment(member["id"], 3, "CHARGE", 30.0, created_at="2024-03-01T00:00:00Z"),
    ]
    stub_history(monkeypatch, history=history)

    response = client.get(f"/api/members/{member['id']}/payments")

    assert response.status_code == 200
    payments = response.get_json()["payments"]
    assert [payment["id"] for payment in payments] == [3, 2, 1]


def test_failing_payments_service_returns_200_with_error_field(client, monkeypatch):
    member = create_member(client)
    stub_history(monkeypatch, error=ApiError(503, "Payments service is unavailable"))

    response = client.get(f"/api/members/{member['id']}/payments")

    assert response.status_code == 200
    body = response.get_json()
    assert body["member"]["id"] == member["id"]
    assert body["payments"] == []
    assert body["paymentHistoryError"] == "Payment history is unavailable"


def test_unknown_member_returns_404_without_calling_payments(client, monkeypatch):
    calls = stub_history(monkeypatch, history=[])

    response = client.get("/api/members/999999/payments")

    assert response.status_code == 404
    assert "message" in response.get_json()
    assert calls == []


def test_empty_history_returns_no_error_field(client, monkeypatch):
    member = create_member(client)
    stub_history(monkeypatch, history=[])

    response = client.get(f"/api/members/{member['id']}/payments")

    assert response.status_code == 200
    body = response.get_json()
    assert body["member"]["id"] == member["id"]
    assert body["payments"] == []
    assert "paymentHistoryError" not in body
