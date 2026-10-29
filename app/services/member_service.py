import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.clients import payments_client
from app.errors import ApiError
from app.extensions import db
from app.models import Member

MEMBERSHIP_PLANS = {"BASIC", "STANDARD", "PREMIUM"}
MEMBER_STATUSES = {"ACTIVE", "INACTIVE", "SUSPENDED"}
PLAN_PRICES = {
    "BASIC": Decimal("29.99"),
    "STANDARD": Decimal("49.99"),
    "PREMIUM": Decimal("79.99"),
}
RENEWAL_PERIOD_DAYS = 30
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def list_members():
    return db.session.scalars(db.select(Member).order_by(Member.id)).all()


def get_member(member_id):
    member = db.session.get(Member, member_id)
    if member is None:
        raise ApiError(404, f"Member with id {member_id} not found")
    return member


def create_member(payload):
    data = _validate_member_payload(payload, partial=False)
    _ensure_email_available(data["email"])

    member = Member(**data)
    db.session.add(member)
    _commit_or_duplicate_email()
    db.session.refresh(member)
    return member


def update_member(member_id, payload):
    member = get_member(member_id)
    updates = _validate_member_payload(payload, partial=True)

    if "email" in updates:
        _ensure_email_available(updates["email"], exclude_id=member.id)

    for field, value in updates.items():
        setattr(member, field, value)

    _commit_or_duplicate_email()
    db.session.refresh(member)
    return member


def renew_member(member_id):
    member = get_member(member_id)

    payments_client.charge(
        {
            "memberId": member.id,
            "amount": float(PLAN_PRICES[member.membership_plan]),
            "reason": f"{member.membership_plan} plan renewal",
        }
    )

    member.renewal_date = datetime.now(UTC).date() + timedelta(days=RENEWAL_PERIOD_DAYS)
    db.session.commit()
    db.session.refresh(member)
    return member


def delete_member(member_id):
    member = get_member(member_id)
    db.session.delete(member)
    db.session.commit()



def _validate_member_payload(payload, partial):
    if not isinstance(payload, dict):
        raise ApiError(400, "Request body must be a JSON object")

    data = {}

    if not partial or "firstName" in payload:
        data["first_name"] = _required_string(payload, "firstName")
    if not partial or "lastName" in payload:
        data["last_name"] = _required_string(payload, "lastName")
    if not partial or "email" in payload:
        email = _required_string(payload, "email")
        if not EMAIL_PATTERN.match(email):
            raise ApiError(400, "email must be a valid email address")
        data["email"] = email

    if "phone" in payload:
        phone = payload["phone"]
        if phone is not None and not isinstance(phone, str):
            raise ApiError(400, "phone must be a string")
        data["phone"] = phone
    elif not partial:
        data["phone"] = None

    if "membershipPlan" in payload:
        data["membership_plan"] = _enum_value(
            payload["membershipPlan"], MEMBERSHIP_PLANS, "membershipPlan"
        )
    elif not partial:
        data["membership_plan"] = "BASIC"

    if "status" in payload:
        data["status"] = _enum_value(payload["status"], MEMBER_STATUSES, "status")
    elif not partial:
        data["status"] = "ACTIVE"

    if "joinedAt" in payload:
        data["joined_at"] = _parse_date(payload["joinedAt"], "joinedAt")

    return data


def _required_string(payload, field):
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, f"{field} is required")
    return value.strip()


def _enum_value(value, allowed, field):
    if not isinstance(value, str) or value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ApiError(400, f"{field} must be one of: {choices}")
    return value


def _parse_date(value, field):
    if not isinstance(value, str):
        raise ApiError(400, f"{field} must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(400, f"{field} must be an ISO date (YYYY-MM-DD)") from exc



def _ensure_email_available(email, exclude_id=None):
    statement = db.select(Member).where(Member.email == email)
    if exclude_id is not None:
        statement = statement.where(Member.id != exclude_id)
    if db.session.scalars(statement).first() is not None:
        raise ApiError(400, "email must be unique")


def _commit_or_duplicate_email():
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ApiError(400, "email must be unique") from exc
