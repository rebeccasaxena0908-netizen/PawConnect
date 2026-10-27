"""
Request bodies (marshmallow schemas). flask-smorest uses them twice:
  1. to check every JSON body before the route runs (wrong shape → 422), and
  2. to draw the forms in the OpenAPI docs at /docs.

Field formats reuse the regex rules in core/validators.py, so a mobile number
is checked by exactly the same pattern in the API, the web app and the desktop app.
The business rules (enough money? case already taken?) stay in core/workflows.py.
"""
from marshmallow import EXCLUDE, Schema, ValidationError, fields, validate

from config import (ALLOCATABLE_FUNDS, ALLOCATION_PURPOSES, ANIMAL_TYPES, CASE_STATUSES,
                    CONTRIBUTION_TYPES, INJURY_LEVELS, PAYMENT_METHODS, SELF_REGISTER_ROLES)
from core import validators as v


def matches(kind: str, optional: bool = False):
    """Marshmallow validator that uses the regex for `kind` from core/validators.py."""
    def check(value):
        if optional and not (value or "").strip():
            return
        if not v.is_valid(kind, value):
            raise ValidationError(v.MESSAGES.get(kind, f"Invalid {kind}."))
    return check


class Base(Schema):
    class Meta:
        unknown = EXCLUDE          # ignore extra keys instead of failing


# ----------------------------------------------------------------------- auth
class LoginIn(Base):
    identifier = fields.String(required=True, metadata={"example": "admin@pawconnect.org"})
    password = fields.String(required=True, metadata={"example": "Admin@123"})


class RegisterStartIn(Base):
    name = fields.String(required=True, validate=matches("name"), metadata={"example": "Neha Gupta"})
    email = fields.String(required=True, validate=matches("email"), metadata={"example": "neha@example.com"})
    mobile = fields.String(load_default="", validate=matches("mobile", optional=True),
                           metadata={"example": "9123456780", "description": "Optional"})
    role = fields.String(required=True, validate=validate.OneOf(SELF_REGISTER_ROLES))
    pincode = fields.String(required=True, validate=matches("pincode"), metadata={"example": "201001"})
    password = fields.String(required=True, metadata={"example": "Good@1234"})
    confirm = fields.String(load_default=None)


class RegisterVerifyIn(Base):
    email = fields.String(required=True, validate=matches("email"), metadata={"example": "neha@example.com"})
    otp = fields.String(required=True, validate=matches("otp"), metadata={"example": "123456"})


class ForgotPasswordIn(Base):
    email = fields.String(required=True, validate=matches("email"))


class ResetPasswordIn(Base):
    email = fields.String(required=True, validate=matches("email"))
    otp = fields.String(required=True, validate=matches("otp"))
    new_password = fields.String(required=True, metadata={"example": "New@12345"})
    confirm = fields.String(load_default=None)


# ----------------------------------------------------------------------- cases
class CaseIn(Base):
    animal_type = fields.String(required=True, validate=validate.OneOf(ANIMAL_TYPES))
    injury_level = fields.String(required=True, validate=validate.OneOf(INJURY_LEVELS))
    description = fields.String(required=True, metadata={"example": "Brown dog limping near Gate 2"})
    pincode = fields.String(required=True, validate=matches("pincode"), metadata={"example": "201001"})
    address = fields.String(load_default="")
    use_network = fields.Boolean(load_default=True, metadata={"description": "Look up exact coordinates online"})


class NoteIn(Base):
    note = fields.String(load_default="")
    estimated_cost = fields.Float(load_default=None, allow_none=True)


class AdvanceIn(Base):
    note = fields.String(load_default="")


class AssignIn(Base):
    rescuer_id = fields.String(required=True)


class StatusIn(Base):
    status = fields.String(required=True, validate=validate.OneOf(CASE_STATUSES))


# ----------------------------------------------------------------------- money
class DonationIn(Base):
    amount = fields.String(required=True, metadata={"example": "1000"})
    contribution_type = fields.String(required=True, validate=validate.OneOf(CONTRIBUTION_TYPES))
    case_id = fields.String(load_default="")
    method = fields.String(required=True, validate=validate.OneOf(PAYMENT_METHODS))
    upi = fields.String(load_default="", metadata={"example": "ananya@okaxis"})
    card_number = fields.String(load_default="", metadata={"description": "Checked, never stored"})
    expiry = fields.String(load_default="")
    cvv = fields.String(load_default="", load_only=True)
    card_name = fields.String(load_default="")


class CheckoutVerifyIn(Base):
    razorpay_order_id = fields.String(required=True)
    razorpay_payment_id = fields.String(required=True)
    razorpay_signature = fields.String(required=True)


class AllocateIn(Base):
    case_id = fields.String(required=True)
    amount = fields.Decimal(required=True, places=2, as_string=True, metadata={"example": "2000"})
    purpose = fields.String(required=True, validate=validate.OneOf(ALLOCATION_PURPOSES))
    source_fund = fields.String(required=True, validate=validate.OneOf(ALLOCATABLE_FUNDS))
    notes = fields.String(load_default="")


# ----------------------------------------------------------------------- adoption
class AnimalIn(Base):
    name = fields.String(required=True, validate=matches("name"))
    species = fields.String(required=True, validate=validate.OneOf(ANIMAL_TYPES))
    breed = fields.String(load_default="Indie")
    age_years = fields.Float(load_default=1.0, validate=validate.Range(0, 40))
    gender = fields.String(load_default="Unknown", validate=validate.OneOf(["Male", "Female", "Unknown"]))
    vaccinated = fields.Boolean(load_default=False)
    sterilized = fields.Boolean(load_default=False)
    temperament = fields.String(load_default="")
    description = fields.String(load_default="")
    case_id = fields.String(load_default="")


class ApplicationIn(Base):
    animal_id = fields.String(required=True)
    answers = fields.Dict(keys=fields.String(), values=fields.String(), required=True)
    reason = fields.String(load_default="")


class ReviewIn(Base):
    decision = fields.String(required=True, validate=validate.OneOf(["Approved", "Rejected"]))


# ----------------------------------------------------------------------- inventory
class InventoryItem(Base):
    item_id = fields.String(load_default="")
    item = fields.String(required=True)
    category = fields.String(load_default="")
    quantity = fields.Raw(required=True)
    unit = fields.String(load_default="")
    reorder_level = fields.Raw(load_default=0)


class InventoryIn(Base):
    items = fields.List(fields.Nested(InventoryItem), required=True)


class EmailTestIn(Base):
    to = fields.String(required=True, validate=matches("email"))


# ----------------------------------------------------------------------- query strings
class RoleQuery(Base):
    role = fields.String(load_default=None)


class AnimalQuery(Base):
    available = fields.Boolean(load_default=False)


class ExportQuery(Base):
    format = fields.String(load_default="csv", validate=validate.OneOf(["csv", "xml"]))
