from datetime import UTC, date, datetime, timedelta

import pytest

from app.errors import ApiError
from app.extensions import db
from app.models import Member
from app.services import member_service

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


class FakeCharge:
    def __init__(self):
        self.payloads = []
        self.error = None

    def __call__(self, payload):
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error
        return {"id": 1, "memberId": payload["memberId"], "type": "CHARGE", "status": "SUCCESS"}


def fake_charge():
    return FakeCharge()


def renew(client, member_id):
    return client.post(f"/api/members/{member_id}/renew")


@pytest.mark.parametrize(
    ("plan", "price"),
    [("BASIC", 29.99), ("STANDARD", 49.99), ("PREMIUM", 79.99)],
)
def test_renew_charges_plan_price_and_sets_renewal_date(client, monkeypatch, plan, price):
    charge = fake_charge()
    monkeypatch.setattr(member_service.payments_client, "charge", charge)
    created = create_member(client, membershipPlan=plan).get_json()

    response = renew(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["renewalDate"] == (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    assert charge.payloads == [
        {
            "memberId": created["id"],
            "amount": price,
            "reason": f"{plan} plan renewal",
        }
    ]
    assert body == client.get(f"/api/members/{created['id']}").get_json()


def test_renew_returns_402_and_leaves_renewal_date_unchanged(client, monkeypatch):
    charge = fake_charge()
    monkeypatch.setattr(member_service.payments_client, "charge", charge)
    created = create_member(client).get_json()

    first = renew(client, created["id"])
    assert first.status_code == 200
    previous_renewal_date = first.get_json()["renewalDate"]
    assert previous_renewal_date is not None

    charge.error = ApiError(402, "payment was declined")
    response = renew(client, created["id"])

    assert response.status_code == 402
    body = response.get_json()
    assert "not renewed" in body["message"]
    assert "renewalDate" not in body
    assert client.get(f"/api/members/{created['id']}").get_json()["renewalDate"] == (
        previous_renewal_date
    )


def test_renew_returns_503_when_payments_service_is_unreachable(client, monkeypatch):
    charge = fake_charge()
    charge.error = ApiError(503, "payments service is unavailable")
    monkeypatch.setattr(member_service.payments_client, "charge", charge)
    created = create_member(client).get_json()

    response = renew(client, created["id"])

    assert response.status_code == 503
    assert client.get(f"/api/members/{created['id']}").get_json()["renewalDate"] is None


def test_renew_returns_404_for_unknown_member_without_calling_payments(client, monkeypatch):
    charge = fake_charge()
    monkeypatch.setattr(member_service.payments_client, "charge", charge)

    response = renew(client, 999999)

    assert response.status_code == 404
    assert charge.payloads == []


def test_renew_records_the_charge_id_as_renewal_payment_id(client, monkeypatch):
    charge = fake_charge()
    monkeypatch.setattr(member_service.payments_client, "charge", charge)
    created = create_member(client).get_json()

    response = renew(client, created["id"])

    assert response.status_code == 200
    assert response.get_json()["renewalPaymentId"] == 1
    assert client.get(f"/api/members/{created['id']}").get_json()["renewalPaymentId"] == 1


def test_new_member_has_no_renewal_payment_id(client):
    created = create_member(client).get_json()

    assert created["renewalPaymentId"] is None
    assert client.get("/api/members").get_json()[0]["renewalPaymentId"] is None


class FakeRefund:
    def __init__(self):
        self.payloads = []
        self.error = None
        self.status = "SUCCESS"

    def __call__(self, payload):
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error
        return {
            "id": 2,
            "memberId": payload["memberId"],
            "amount": payload["amount"],
            "type": "REFUND",
            "status": self.status,
            "relatedPaymentId": payload["relatedPaymentId"],
        }


def fake_refund():
    return FakeRefund()


def stub_refund(monkeypatch):
    refund = fake_refund()
    monkeypatch.setattr(member_service.payments_client, "refund", refund)
    return refund


def set_paid_period(app, member_id, days_remaining, payment_id=41):
    with app.app_context():
        member = db.session.get(Member, member_id)
        member.renewal_date = date.today() + timedelta(days=days_remaining)
        member.renewal_payment_id = payment_id
        db.session.commit()


def member_with_paid_period(client, app, days_remaining=30, payment_id=41, **overrides):
    created = create_member(client, **overrides).get_json()
    set_paid_period(app, created["id"], days_remaining, payment_id)
    return created


def cancel(client, member_id, **body):
    return client.post(f"/api/members/{member_id}/cancel", json=body)


def test_cancel_refunds_the_unused_period_and_deactivates_the_member(client, app, monkeypatch):
    refund = stub_refund(monkeypatch)
    created = member_with_paid_period(client, app, days_remaining=30, payment_id=41)

    response = cancel(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["memberId"] == created["id"]
    assert body["status"] == "SUCCESS"
    assert body["amount"] == 79.99
    assert body["paymentId"] == 2
    assert body["refundFollowUpRequired"] is False
    assert refund.payloads == [
        {
            "memberId": created["id"],
            "amount": 79.99,
            "reason": "PREMIUM plan cancellation refund",
            "relatedPaymentId": 41,
        }
    ]
    assert client.get(f"/api/members/{created['id']}").get_json()["status"] == "INACTIVE"


def test_cancel_rounds_the_refund_to_cents(client, app, monkeypatch):
    refund = stub_refund(monkeypatch)
    basic = member_with_paid_period(
        client, app, days_remaining=15, email="basic@example.com", membershipPlan="BASIC"
    )
    standard = member_with_paid_period(
        client, app, days_remaining=7, email="standard@example.com", membershipPlan="STANDARD"
    )

    cancel(client, basic["id"])
    cancel(client, standard["id"])

    assert refund.payloads[0]["amount"] == 15.0
    assert refund.payloads[1]["amount"] == 11.66


def test_cancel_caps_the_refund_at_one_period(client, app, monkeypatch):
    refund = stub_refund(monkeypatch)
    created = member_with_paid_period(client, app, days_remaining=45)

    response = cancel(client, created["id"])

    assert response.status_code == 200
    assert response.get_json()["amount"] == 79.99
    assert refund.payloads == [
        {
            "memberId": created["id"],
            "amount": 79.99,
            "reason": "PREMIUM plan cancellation refund",
            "relatedPaymentId": 41,
        }
    ]


def test_cancel_links_the_refund_to_the_renewal_charge(client, monkeypatch):
    charge = fake_charge()
    monkeypatch.setattr(member_service.payments_client, "charge", charge)
    refund = stub_refund(monkeypatch)
    created = create_member(client).get_json()
    renewal_payment_id = renew(client, created["id"]).get_json()["renewalPaymentId"]
    assert renewal_payment_id == 1

    response = cancel(client, created["id"])

    body = response.get_json()
    assert body["status"] == "SUCCESS"
    assert body["amount"] == 79.99
    assert body["paymentId"] == 2
    assert refund.payloads[0]["relatedPaymentId"] == renewal_payment_id


def test_cancel_reports_pending_without_follow_up(client, app, monkeypatch):
    refund = fake_refund()
    refund.status = "PENDING"
    monkeypatch.setattr(member_service.payments_client, "refund", refund)
    created = member_with_paid_period(client, app)

    response = cancel(client, created["id"], status="PENDING")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "PENDING"
    assert body["refundFollowUpRequired"] is False
    assert body["paymentId"] == 2
    assert refund.payloads[0]["status"] == "PENDING"


def test_cancel_reports_failed_with_follow_up_and_keeps_member_inactive(
    client, app, monkeypatch
):
    refund = fake_refund()
    refund.error = ApiError(422, "refund exceeds the linked charge")
    monkeypatch.setattr(member_service.payments_client, "refund", refund)
    created = member_with_paid_period(client, app)

    response = cancel(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "FAILED"
    assert body["refundFollowUpRequired"] is True
    assert "Follow up required" in body["message"]
    assert client.get(f"/api/members/{created['id']}").get_json()["status"] == "INACTIVE"


def test_cancel_reports_a_failed_refund_response_with_follow_up(client, app, monkeypatch):
    refund = fake_refund()
    refund.status = "FAILED"
    monkeypatch.setattr(member_service.payments_client, "refund", refund)
    created = member_with_paid_period(client, app)

    response = cancel(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "FAILED"
    assert body["refundFollowUpRequired"] is True
    assert "Follow up required" in body["message"]
    assert client.get(f"/api/members/{created['id']}").get_json()["status"] == "INACTIVE"


@pytest.mark.parametrize("days_remaining", [0, -5])
def test_cancel_is_not_eligible_when_the_renewal_date_is_today_or_past(
    client, app, monkeypatch, days_remaining
):
    refund = stub_refund(monkeypatch)
    created = member_with_paid_period(client, app, days_remaining=days_remaining)

    response = cancel(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "NOT_ELIGIBLE"
    assert body["amount"] is None
    assert body["paymentId"] is None
    assert body["refundFollowUpRequired"] is False
    assert refund.payloads == []
    assert client.get(f"/api/members/{created['id']}").get_json()["status"] == "INACTIVE"


def test_cancel_without_a_paid_period_writes_no_refund(client, monkeypatch):
    refund = stub_refund(monkeypatch)
    created = create_member(client).get_json()
    assert created["renewalPaymentId"] is None

    response = cancel(client, created["id"])

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "NOT_ELIGIBLE"
    assert body["amount"] is None
    assert body["paymentId"] is None
    assert body["refundFollowUpRequired"] is False
    assert refund.payloads == []
    assert client.get(f"/api/members/{created['id']}").get_json()["status"] == "INACTIVE"


def test_cancel_for_an_already_inactive_member_is_not_eligible_and_not_refunded_again(
    client, app, monkeypatch
):
    refund = stub_refund(monkeypatch)
    created = member_with_paid_period(client, app)
    client.put(f"/api/members/{created['id']}", json={"status": "INACTIVE"})

    response = cancel(client, created["id"])

    assert response.status_code == 200
    assert response.get_json()["status"] == "NOT_ELIGIBLE"
    assert refund.payloads == []


def test_cancel_returns_404_for_an_unknown_member_without_calling_payments(client, monkeypatch):
    refund = stub_refund(monkeypatch)

    response = cancel(client, 999999)

    assert response.status_code == 404
    assert refund.payloads == []


def test_cancel_is_idempotent_and_refunds_only_once(client, app, monkeypatch):
    refund = stub_refund(monkeypatch)
    created = member_with_paid_period(client, app)

    first = cancel(client, created["id"])
    second = cancel(client, created["id"])

    assert first.status_code == 200
    assert first.get_json()["status"] == "SUCCESS"
    assert second.status_code == 200
    assert second.get_json()["status"] == "NOT_ELIGIBLE"
    assert len(refund.payloads) == 1


def test_cancel_rejects_an_unknown_refund_status(client, app, monkeypatch):
    refund = stub_refund(monkeypatch)
    created = member_with_paid_period(client, app)

    response = cancel(client, created["id"], status="REFUNDED")

    assert response.status_code == 400
    assert "status" in response.get_json()["message"]
    assert refund.payloads == []
