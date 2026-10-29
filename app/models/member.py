from datetime import UTC, date, datetime

from app.extensions import db


def _utcnow():
    return datetime.now(UTC)


def _iso_datetime(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class Member(db.Model):
    __tablename__ = "members"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(50), nullable=True)
    membership_plan = db.Column(
        db.Enum("BASIC", "STANDARD", "PREMIUM", name="membership_plan"),
        nullable=False,
        default="BASIC",
    )
    status = db.Column(
        db.Enum("ACTIVE", "INACTIVE", "SUSPENDED", name="membership_status"),
        nullable=False,
        default="ACTIVE",
    )
    joined_at = db.Column(db.Date, nullable=False, default=date.today)
    renewal_date = db.Column(db.Date, nullable=True)
    renewal_payment_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "firstName": self.first_name,
            "lastName": self.last_name,
            "email": self.email,
            "phone": self.phone,
            "membershipPlan": self.membership_plan,
            "status": self.status,
            "joinedAt": self.joined_at.isoformat() if self.joined_at else None,
            "renewalDate": self.renewal_date.isoformat() if self.renewal_date else None,
            "renewalPaymentId": self.renewal_payment_id,
            "createdAt": _iso_datetime(self.created_at),
            "updatedAt": _iso_datetime(self.updated_at),
        }
