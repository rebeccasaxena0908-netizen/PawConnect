"""
Business workflows shared by the web app and the desktop console.

The interfaces only collect input and show results; every rule (validation,
status changes, fund limits, adoption decisions, audit logging) lives here.

Steps that must happen together run inside `with dh.transaction() as conn:` –
if any step fails, the database rolls all of them back.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from sqlalchemy.exc import IntegrityError

from analytics import data_handler as dh
from config import (ALLOCATABLE_FUNDS, ALLOCATION_PURPOSES, ALLOWED_PHOTO_TYPES, ANIMAL_TYPES,
                    BASE_DIR, CASE_STATUSES, CONTRIBUTION_TYPES, DECLINED_TEST_CARD,
                    DECLINED_TEST_UPI, INJURY_LEVELS, MAX_DONATION, MAX_PHOTO_MB, MIN_DONATION,
                    PAYMENT_METHODS, ROLES, SELF_REGISTER_ROLES)
from core import validators as v
from core.models import (QUESTIONNAIRE, AdoptionApplication, Animal, DonationTransaction,
                         FundAllocation, RescueCase, User, hash_password, now_str)
from services.api_service import PaymentGatewaySimulator, geocode_pincode
from services import email_service
from services.notification_service import OTPLimitError, OTPManager


class ValidationError(Exception):
    """Raised with a list of human-readable problems."""

    def __init__(self, problems: list[str] | str):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(self.problems))


class Conflict(ValidationError):
    """The request is fine but clashes with the current state (already taken, not enough money...)."""


class NotFound(ValidationError):
    """The record asked for doesn't exist."""


class PaymentDeclined(ValidationError):
    """The bank / gateway said no. The failed attempt is still recorded."""


class DeliveryFailed(ValidationError):
    """An e-mail that the user is waiting for (an OTP) could not be sent."""


class GatewayError(ValidationError):
    """The payment gateway refused us (wrong keys) or couldn't be reached."""


class PermissionDenied(Exception):
    pass


def _require(user: User, permission: str) -> None:
    if not user.can(permission):
        raise PermissionDenied(f"{user.role}s can't {permission.replace('_', ' ')}.")


# ======================================================================= users
def get_user(user_id: str, conn=None) -> User | None:
    row = dh.find_row("users", "user_id", user_id, conn=conn)
    return User.from_dict(row) if row else None


def find_user(identifier: str) -> User | None:
    """Look up by e-mail (any case) or mobile number."""
    df = dh.load_table("users")
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    email = identifier.lower()
    mobile = v.normalize("mobile", identifier)
    by_mobile = (df["mobile"] == mobile) & (df["mobile"] != "")      # an empty mobile never matches
    match = df[(df["email"].str.lower() == email) | by_mobile]
    return None if match.empty else User.from_dict(match.iloc[0].to_dict())


def check_registration(name: str, email: str, mobile: str, role: str, pincode: str,
                       password: str, confirm: str | None = None, allow_admin: bool = False) -> dict:
    """
    Validate a sign-up form. Returns the cleaned values or raises ValidationError.
    The e-mail is required (it is where the OTP goes); the mobile number is optional,
    but when given it must be a valid Indian number that no one else uses.
    """
    problems = []
    mobile = (mobile or "").strip()
    fields_to_check = [("name", name), ("email", email), ("pincode", pincode)]
    if mobile:
        fields_to_check.append(("mobile", mobile))
    for kind, value in fields_to_check:
        ok, message = v.validate(kind, value)
        if not ok:
            problems.append(message)
    allowed = ROLES if allow_admin else SELF_REGISTER_ROLES
    if role not in allowed:
        problems.append("Please choose a valid role.")
    weak = v.password_problems(password)
    if weak:
        problems.append("Password needs " + ", ".join(weak) + ".")
    if confirm is not None and password != confirm:
        problems.append("The two passwords don't match.")
    clean = {"name": v.sanitize_text(name, 60), "email": v.normalize("email", email),
             "mobile": v.normalize("mobile", mobile), "pincode": v.normalize("pincode", pincode),
             "role": role}
    if not problems:
        df = dh.load_table("users")
        if (df["email"].str.lower() == clean["email"]).any():
            problems.append("An account with this e-mail already exists.")
        if clean["mobile"] and (df["mobile"] == clean["mobile"]).any():
            problems.append("An account with this mobile number already exists.")
    if problems:
        raise ValidationError(problems)
    return clean


def register_user(name: str, email: str, mobile: str, role: str, pincode: str, password: str,
                  allow_admin: bool = False) -> User:
    """Create the account. Call only after the OTP has been verified."""
    clean = check_registration(name, email, mobile, role, pincode, password,
                               allow_admin=allow_admin)
    try:
        with dh.transaction() as conn:
            row = {**clean, "user_id": dh.next_id("users", "U", conn=conn),
                   "password_hash": hash_password(password), "created_at": now_str(), "verified": "yes"}
            user = User.from_dict(row)
            dh.append_row("users", user.to_dict(), conn=conn)
            dh.log_event(user.user_id, role, "USER_REGISTERED",
                         f"{user.name} registered as {role} (e-mail verified)", conn=conn)
    except IntegrityError:
        # UNIQUE(email) / UNIQUE(mobile) caught someone registering at the same moment.
        raise Conflict("An account with this e-mail or mobile number already exists.") from None
    email_service.send_welcome(user.email, user.name, user.role)      # in the background
    return user


# ----------------------------------------------------------------------- one-time passwords by e-mail
def _send_code(otp: OTPManager, purpose: str, email: str) -> str:
    """Create a code for (purpose, email), e-mail it and wait for the result. Returns the code."""
    key = f"{purpose}:{email}"
    try:
        code = otp.generate(key, address=email)
    except OTPLimitError as error:
        raise ValidationError(str(error)) from None
    result = email_service.send_otp(email, code, "sign up" if purpose == "signup" else "password reset")
    if not result["ok"]:
        otp.discard(key)
        raise DeliveryFailed(f"Could not send the e-mail – please try again. ({result['error']})")
    return code


def send_signup_otp(otp: OTPManager, email: str) -> str:
    """E-mail a sign-up code to the (already checked) address. Returns the code (shown only in demo mode)."""
    return _send_code(otp, "signup", v.normalize("email", email))


def verify_signup_otp(otp: OTPManager, email: str, code: str) -> None:
    ok, message = otp.verify(f"signup:{v.normalize('email', email)}", code)
    if not ok:
        raise ValidationError(message)


def request_password_reset(otp: OTPManager, email: str) -> str | None:
    """
    Forgot password, step 1. Sends a code only if an account has this e-mail, but the
    caller always shows the same message, so nobody can test which e-mails exist.
    Returns the code (for demo mode) or None.
    """
    email = v.normalize("email", email)
    if not v.is_valid("email", email):
        raise ValidationError(v.MESSAGES["email"])
    user = find_user(email)
    dh.log_event(user.user_id if user else email[:60], user.role if user else "Unknown",
                 "PASSWORD_RESET_REQUESTED", f"Reset code requested for {v.mask_email(email)}")
    if user is None:
        return None
    return _send_code(otp, "reset", email)


def reset_password(otp: OTPManager, email: str, code: str, new_password: str,
                   confirm: str | None = None) -> User:
    """Forgot password, step 2: check the code and the new password, then save it."""
    email = v.normalize("email", email)
    problems = []
    weak = v.password_problems(new_password)
    if weak:
        problems.append("Password needs " + ", ".join(weak) + ".")
    if confirm is not None and new_password != confirm:
        problems.append("The two passwords don't match.")
    if problems:
        raise ValidationError(problems)
    ok, message = otp.verify(f"reset:{email}", code)
    user = find_user(email)
    if not ok or user is None:
        raise ValidationError(message if not ok else "No account uses this e-mail.")
    with dh.transaction() as conn:
        dh.update_row("users", "user_id", user.user_id, {"password_hash": hash_password(new_password)}, conn=conn)
        dh.log_event(user.user_id, user.role, "PASSWORD_RESET", f"{user.name} set a new password (e-mail verified)",
                     conn=conn)
    return user


def authenticate(identifier: str, password: str) -> User | None:
    user = find_user(identifier)
    if user and user.check_password(password):
        dh.log_event(user.user_id, user.role, "LOGIN", f"{user.name} signed in")
        return user
    dh.log_event(identifier[:60] if identifier else "unknown", "Unknown", "LOGIN_FAILED",
                 "Wrong e-mail/mobile or password")
    return None


def list_users(role: str | None = None) -> pd.DataFrame:
    df = dh.load_table("users").drop(columns=["password_hash"])
    return df if role is None else df[df["role"] == role]


def rescuer_choices() -> dict[str, str]:
    df = list_users("Rescuer")
    return {r.user_id: f"{r.name} ({r.pincode})" for r in df.itertuples()}


# ======================================================================= rescue cases
def create_rescue_case(reporter: User, animal_type: str, injury_level: str, description: str,
                       pincode: str, address: str = "", photo_bytes: bytes | None = None,
                       photo_name: str = "", use_network: bool = True) -> RescueCase:
    _require(reporter, "report_sos")
    problems = []
    if animal_type not in ANIMAL_TYPES:
        problems.append("Choose the type of animal.")
    if injury_level not in INJURY_LEVELS:
        problems.append("Choose an injury level.")
    clean_description = v.sanitize_text(description, 500)
    if len(clean_description) < 10:
        problems.append("Describe the animal and its injury in at least 10 characters.")
    ok, message = v.validate("pincode", pincode)
    if not ok:
        problems.append(message)
    if photo_bytes:
        problems += _check_photo(photo_bytes, photo_name)
    if problems:
        raise ValidationError(problems)

    pincode = v.normalize("pincode", pincode)
    location = geocode_pincode(pincode, use_network=use_network)
    with dh.transaction() as conn:
        case = RescueCase(
            case_id=dh.next_id("rescue_cases", "RC-", conn=conn), reporter_id=reporter.user_id,
            animal_type=animal_type, injury_level=injury_level, description=clean_description,
            pincode=pincode, address=v.sanitize_text(address, 150),
            latitude=str(location["latitude"]), longitude=str(location["longitude"]),
            location_source=location["source"],
        )
        if photo_bytes:
            case.photo_path = _store_photo(case.case_id, photo_bytes, photo_name)
        dh.append_row("rescue_cases", case.to_dict(), conn=conn)
        dh.log_event(reporter.user_id, reporter.role, "SOS_REPORTED",
                     f"{case.case_id}: {injury_level} {animal_type.lower()} at {pincode} ({location['source']})",
                     conn=conn)
    return case


def _check_photo(photo_bytes: bytes, photo_name: str) -> list[str]:
    problems = []
    if Path(photo_name).suffix.lower().lstrip(".") not in ALLOWED_PHOTO_TYPES:
        problems.append("Photo must be JPG, PNG or WEBP.")
    if len(photo_bytes) > MAX_PHOTO_MB * 1024 * 1024:
        problems.append(f"Photo must be smaller than {MAX_PHOTO_MB} MB.")
    return problems


def _store_photo(case_id: str, photo_bytes: bytes, photo_name: str) -> str:
    """Save the upload as data/uploads/<case id>.<ext> and return the path to keep in the table."""
    path = dh.safe_photo_path(case_id, photo_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(photo_bytes)
    return str(path.relative_to(BASE_DIR)) if path.is_relative_to(BASE_DIR) else str(path)


def attach_case_photo(case_id: str, actor: User, photo_bytes: bytes, photo_name: str) -> RescueCase:
    """Add or replace the photo of a case (the reporter, its rescuer or an admin)."""
    case = load_case(case_id)
    allowed = (actor.user_id in (case.reporter_id, case.rescuer_id)) or actor.can("assign_case")
    if not allowed:
        raise PermissionDenied("Only the reporter, the assigned rescuer or an admin can add a photo.")
    if not photo_bytes:
        raise ValidationError("Choose a photo to upload.")
    problems = _check_photo(photo_bytes, photo_name)
    if problems:
        raise ValidationError(problems)
    with dh.transaction() as conn:
        case.photo_path = _store_photo(case_id, photo_bytes, photo_name)
        case.updated_at = now_str()
        _save_case(case, conn)
        dh.log_event(actor.user_id, actor.role, "CASE_PHOTO", f"{case_id}: photo uploaded", conn=conn)
    return case


def case_photo_file(case_id: str) -> Path | None:
    case = load_case(case_id)
    if case.photo_path and (BASE_DIR / case.photo_path).exists():
        return BASE_DIR / case.photo_path
    return None


def load_case(case_id: str, conn=None) -> RescueCase:
    row = dh.find_row("rescue_cases", "case_id", case_id, conn=conn)
    if row is None:
        raise NotFound(f"Case {case_id} was not found.")
    return RescueCase.from_dict(row)


def list_cases() -> pd.DataFrame:
    return dh.load_table("rescue_cases")


def _save_case(case: RescueCase, conn=None, expected_status: str | None = None) -> None:
    """Write the case back. With expected_status the UPDATE only happens if nobody changed it meanwhile."""
    expected = {"status": expected_status} if expected_status else None
    if not dh.update_row("rescue_cases", "case_id", case.case_id, case.to_dict(), conn=conn,
                         expected=expected):
        raise Conflict(f"{case.case_id} was changed by someone else just now. Refresh and try again.")


def accept_case(case_id: str, rescuer: User) -> RescueCase:
    _require(rescuer, "accept_case")
    case = load_case(case_id)
    if case.status != "Reported":
        raise Conflict(f"{case_id} has already been taken ({case.status}).")
    case.advance(rescuer_id=rescuer.user_id)
    with dh.transaction() as conn:
        # UPDATE ... WHERE case_id = ? AND status = 'Reported' – if another rescuer
        # got there first, no row matches and we report the clash instead.
        taken = not dh.update_row("rescue_cases", "case_id", case_id, case.to_dict(), conn=conn,
                                  expected={"status": "Reported"})
        if taken:
            raise Conflict(f"{case_id} has just been accepted by another rescuer.")
        dh.log_event(rescuer.user_id, rescuer.role, "CASE_ACCEPTED", f"{case_id} accepted by {rescuer.name}",
                     conn=conn)
    return case


def assign_case(case_id: str, rescuer_id: str, admin: User) -> RescueCase:
    _require(admin, "assign_case")
    rescuer = get_user(rescuer_id)
    if rescuer is None or rescuer.role != "Rescuer":
        raise ValidationError("Choose a registered rescuer.")
    case = load_case(case_id)
    old = case.status
    if case.status == "Reported":
        case.advance(rescuer_id=rescuer_id)
    else:
        case.rescuer_id = rescuer_id
        case.updated_at = now_str()
    with dh.transaction() as conn:
        _save_case(case, conn, expected_status=old)
        dh.log_event(admin.user_id, admin.role, "CASE_ASSIGNED", f"{case_id} assigned to {rescuer.name}",
                     conn=conn)
    return case


def advance_case(case_id: str, actor: User, note: str = "") -> RescueCase:
    _require(actor, "update_case")
    case = load_case(case_id)
    if case.status == "Reported" and actor.role == "Rescuer":
        raise ValidationError("Accept the case first.")
    if actor.role == "Rescuer" and case.rescuer_id != actor.user_id:
        raise PermissionDenied("You can only update cases assigned to you.")
    old = case.status
    try:
        new = case.advance(rescuer_id=case.rescuer_id or None)
    except ValueError as error:
        raise ValidationError(str(error)) from None
    if note:
        case.add_note(v.sanitize_text(note, 300), actor.name)
    with dh.transaction() as conn:
        _save_case(case, conn, expected_status=old)      # two clicks can't skip a stage
        dh.log_event(actor.user_id, actor.role, "CASE_STATUS", f"{case_id}: {old} → {new}", conn=conn)
    reporter = get_user(case.reporter_id)
    if reporter:                    # e-mail the person who reported the animal (in the background)
        email_service.send_case_update(reporter.email, reporter.name, case_id, new)
    return case


def set_case_status(case_id: str, status: str, admin: User) -> RescueCase:
    """Admin correction: set any status directly."""
    _require(admin, "assign_case")
    if status not in CASE_STATUSES:
        raise ValidationError("Unknown status.")
    case = load_case(case_id)
    if status != "Reported" and not case.rescuer_id:
        raise ValidationError("Assign a rescuer before moving the case on.")
    old, case.status, case.updated_at = case.status, status, now_str()
    if status == "Reported":
        case.assigned_at = ""
    with dh.transaction() as conn:
        _save_case(case, conn, expected_status=old)
        dh.log_event(admin.user_id, admin.role, "CASE_STATUS", f"{case_id}: {old} → {status} (admin)",
                     conn=conn)
    return case


def add_case_note(case_id: str, actor: User, note: str, estimated_cost: float | None = None) -> RescueCase:
    _require(actor, "update_case")
    case = load_case(case_id)
    if actor.role == "Rescuer" and case.rescuer_id != actor.user_id:
        raise PermissionDenied("You can only update cases assigned to you.")
    note = v.sanitize_text(note, 300)
    if note:
        case.add_note(note, actor.name)
    if estimated_cost is not None:
        if not 0 <= estimated_cost <= MAX_DONATION:
            raise ValidationError("Estimated cost looks wrong.")
        case.estimated_cost = f"{estimated_cost:.0f}"
        case.updated_at = now_str()
    with dh.transaction() as conn:
        _save_case(case, conn)
        dh.log_event(actor.user_id, actor.role, "CASE_NOTE", f"{case_id}: note/cost updated", conn=conn)
    return case


# ======================================================================= donations
def _check_payment(method: str, details: dict) -> tuple[str, str]:
    """Validate payment fields. Returns (account key for the gateway, masked account)."""
    if method == "UPI":
        upi = v.normalize("upi", details.get("upi", ""))
        ok, message = v.validate("upi", upi)
        if not ok:
            raise ValidationError(message)
        return upi, v.mask_upi(upi)
    if method == "Card":
        number = v.normalize("card", details.get("card_number", ""))
        problems = []
        if not v.is_valid("card", number) or not v.luhn_check(number):
            problems.append("That card number isn't valid.")
        if not v.expiry_ok(details.get("expiry", "")):
            problems.append("Card expiry must be MM/YY and not in the past.")
        if not v.is_valid("cvv", details.get("cvv", "")):
            problems.append(v.MESSAGES["cvv"])
        if not v.is_valid("name", details.get("card_name", "")):
            problems.append("Enter the name printed on the card.")
        if problems:
            raise ValidationError(problems)
        return number, v.mask_card(number)
    raise ValidationError("Choose UPI or card.")


def parse_amount(raw) -> Decimal:
    """Text such as "2,500" or "₹499.50" → Decimal (money is never a float)."""
    text = str(raw).replace(",", "").replace("₹", "").strip()
    if not v.is_valid("amount", text):
        raise ValidationError(v.MESSAGES["amount"])
    amount = Decimal(text)
    if not MIN_DONATION <= amount <= MAX_DONATION:
        raise ValidationError(f"Amount must be between ₹{MIN_DONATION} and ₹{MAX_DONATION:,}.")
    return amount


def make_donation(donor: User, amount, contribution_type: str, method: str, details: dict,
                  case_id: str = "") -> tuple[DonationTransaction, str]:
    """
    Validate → create gateway order → capture → verify HMAC signature → parse JSON
    → save to donations.csv → send receipt. Card numbers and CVVs are never stored.
    """
    amount, contribution_type, case_id = _check_donation(donor, amount, contribution_type, case_id)
    if method not in PAYMENT_METHODS:
        raise ValidationError("Choose UPI or card.")
    account_key, masked = _check_payment(method, details)

    tx = DonationTransaction(
        transaction_id=DonationTransaction.new_id(), donor_id=donor.user_id,
        donor_name=donor.name, donor_email=donor.email, amount=amount,
        contribution_type=contribution_type, case_id=case_id, method=method,
        masked_account=masked,
    )
    gateway = PaymentGatewaySimulator(declined_accounts={DECLINED_TEST_CARD, DECLINED_TEST_UPI})
    order = gateway.create_order(amount, receipt=tx.transaction_id)
    body, signature = gateway.capture(order, method, account_key, masked)
    if not gateway.verify_signature(body, signature):
        raise ValidationError("Payment response could not be verified. Nothing was charged.")
    result = gateway.parse_webhook(body)
    tx.payment_ref = result["payment_id"]
    tx.status = "Success" if result["status"] == "captured" else "Failed"
    with dh.transaction() as conn:            # the donation and its audit entry go in together
        dh.append_row("donations", tx.to_dict(), conn=conn)
        dh.log_event(donor.user_id, donor.role, "DONATION_" + tx.status.upper(),
                     f"{tx.transaction_id}: ₹{amount:,.2f} to {contribution_type}"
                     + (f" ({case_id})" if case_id else "") + f" via {method}", conn=conn)
    if not tx.succeeded:
        raise PaymentDeclined(result.get("error") or "Payment failed.")
    receipt = email_service.send_receipt(tx.to_dict())
    return tx, receipt


# ----------------------------------------------------------------------- real (test-mode) gateway
def start_online_donation(donor: User, amount, contribution_type: str, gateway,
                          case_id: str = "") -> tuple[DonationTransaction, dict]:
    """
    Step 1 of a Razorpay payment: create the order at Razorpay and save a
    'Pending' donation. The donor then pays on Razorpay's own checkout page,
    so card numbers never reach our server at all.
    """
    amount, contribution_type, case_id = _check_donation(donor, amount, contribution_type, case_id)
    tx = DonationTransaction(
        transaction_id=DonationTransaction.new_id(), donor_id=donor.user_id, donor_name=donor.name,
        donor_email=donor.email, amount=amount, contribution_type=contribution_type, case_id=case_id,
        method="Razorpay", masked_account="Razorpay Checkout", status="Pending",
    )
    try:
        order = gateway.create_order(amount, receipt=tx.transaction_id,
                                     notes={"fund": contribution_type, "case_id": case_id})
    except Exception as error:      # noqa: BLE001 – razorpay raises several of its own error types
        text = str(error)
        if "auth" in text.lower() or "key" in text.lower():
            raise GatewayError(["Razorpay rejected the API keys.",
                                "Check RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env – the secret is a "
                                "different random string, shown once when you generate the test key."]) from None
        raise GatewayError(f"Razorpay couldn't create the order ({error.__class__.__name__}). "
                           "Try UPI/card (sandbox) or try again later.") from None
    tx.payment_ref = order["id"]
    with dh.transaction() as conn:
        dh.append_row("donations", tx.to_dict(), conn=conn)
        dh.log_event(donor.user_id, donor.role, "DONATION_PENDING",
                     f"{tx.transaction_id}: ₹{amount:,.2f} order {order['id']} created", conn=conn)
    return tx, order


def settle_online_payment(order_id: str, payment_id: str, succeeded: bool,
                          source: str = "checkout") -> dict | None:
    """
    Step 2: called only AFTER the gateway's signature has been verified.
    Marks the Pending donation as Success/Failed exactly once – a webhook that
    arrives after the checkout callback (or twice) changes nothing.
    Returns the donation row, or None if no donation has this order id.
    """
    donations = dh.load_table("donations")
    match = donations[donations["payment_ref"].isin([order_id, payment_id])]
    if match.empty:
        return None
    row = match.iloc[0].to_dict()
    status = "Success" if succeeded else "Failed"
    with dh.transaction() as conn:
        changed = dh.update_row("donations", "transaction_id", row["transaction_id"],
                                {"status": status, "payment_ref": payment_id or order_id},
                                conn=conn, expected={"status": "Pending"})
        if changed:
            dh.log_event(row["donor_id"], "Donor", "DONATION_" + status.upper(),
                         f"{row['transaction_id']}: ₹{float(row['amount']):,.2f} via Razorpay ({source})",
                         conn=conn)
    row = dh.find_row("donations", "transaction_id", row["transaction_id"])
    if changed and succeeded:
        email_service.send_receipt(row)
    return row


def _check_donation(donor: User, amount, contribution_type: str, case_id: str) -> tuple[Decimal, str, str]:
    """Checks shared by the sandbox and the Razorpay flow."""
    _require(donor, "donate")
    amount = parse_amount(amount)
    if contribution_type not in CONTRIBUTION_TYPES:
        raise ValidationError("Choose a fund.")
    if contribution_type == "Specific Medical Case":
        if not case_id:
            raise ValidationError("Choose the rescue case you want to support.")
        load_case(case_id)
    else:
        case_id = ""
    return amount, contribution_type, case_id


def get_donation(transaction_id: str) -> dict:
    row = dh.find_row("donations", "transaction_id", transaction_id)
    if row is None:
        raise NotFound("Donation not found.")
    return row


def donation_receipt(transaction_id: str) -> str:
    from services.notification_service import build_receipt
    row = dh.find_row("donations", "transaction_id", transaction_id)
    if row is None:
        raise NotFound("Receipt not found.")
    return build_receipt(row)


def list_donations(donor: User | None = None) -> pd.DataFrame:
    """All donations, or only one donor's."""
    df = dh.load_table("donations")
    return df if donor is None else df[df["donor_id"] == donor.user_id]


# ======================================================================= fund allocation
def funds_available(source_fund: str, conn=None) -> Decimal:
    """Exact balance of a fund, worked out by the database (SUM of paise)."""
    return dh.fund_balance(source_fund, conn=conn)


def allocate_funds(admin: User, case_id: str, amount, purpose: str, source_fund: str,
                   notes: str = "") -> FundAllocation:
    _require(admin, "allocate_funds")
    if source_fund not in ALLOCATABLE_FUNDS:
        raise ValidationError("Choose the fund to allocate from.")
    if purpose not in ALLOCATION_PURPOSES:
        raise ValidationError("Choose what the money is for.")
    try:
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (TypeError, ValueError, InvalidOperation):
        raise ValidationError("Enter an amount.") from None
    if amount <= 0:
        raise ValidationError("Amount must be more than zero.")
    load_case(case_id)        # 404 before we take any lock
    with dh.transaction() as conn:
        # Lock first, then read the balance: a second allocation running at the same
        # moment has to wait here, and will then see the reduced balance.
        dh.lock_table(conn, "allocations")
        available = funds_available(source_fund, conn)
        if amount > available:
            raise Conflict(f"Only ₹{available:,.2f} is available in the {source_fund}.")
        case = load_case(case_id, conn)
        allocation = FundAllocation(
            allocation_id=dh.next_id("allocations", "AL-", conn=conn), case_id=case_id,
            source_fund=source_fund, amount=amount, purpose=purpose,
            allocated_by=admin.user_id, notes=v.sanitize_text(notes, 200),
        )
        dh.append_row("allocations", allocation.to_dict(), conn=conn)
        case.add_note(f"₹{amount:,.0f} allocated from {source_fund} for {purpose.lower()}", admin.name)
        _save_case(case, conn)
        dh.log_event(admin.user_id, admin.role, "FUNDS_ALLOCATED",
                     f"{allocation.allocation_id}: ₹{amount:,.2f} from {source_fund} to {case_id} ({purpose})",
                     conn=conn)
    return allocation


# ======================================================================= adoption
def available_animals() -> pd.DataFrame:
    df = dh.load_table("animals")
    return df[df["status"] == "Available"]


def submit_application(applicant: User, animal_id: str, answers: dict[str, str],
                       reason: str = "") -> AdoptionApplication:
    _require(applicant, "apply_adoption")
    animal = dh.find_row("animals", "animal_id", animal_id)
    if animal is None:
        raise NotFound("Animal not found.")
    if animal["status"] != "Available":
        raise Conflict("This animal is no longer available.")
    missing = [QUESTIONNAIRE[k]["question"] for k in QUESTIONNAIRE
               if answers.get(k) not in QUESTIONNAIRE[k]["options"]]
    if missing:
        raise ValidationError(["Please answer: " + q for q in missing])
    apps = dh.load_table("adoption_applications")
    duplicate = apps[(apps["applicant_id"] == applicant.user_id) & (apps["animal_id"] == animal_id)
                     & apps["status"].isin(["Pre-Approved", "Under Review"])]
    if not duplicate.empty:
        raise Conflict("You already have an open application for this animal.")
    with dh.transaction() as conn:
        application = AdoptionApplication(
            application_id=dh.next_id("adoption_applications", "AP-", conn=conn),
            applicant_id=applicant.user_id, applicant_name=applicant.name, animal_id=animal_id,
            reason=v.sanitize_text(reason, 400), **{k: answers[k] for k in QUESTIONNAIRE},
        )
        dh.append_row("adoption_applications", application.to_dict(), conn=conn)
        dh.log_event(applicant.user_id, applicant.role, "ADOPTION_APPLIED",
                     f"{application.application_id} for {animal['name']} ({animal_id}): "
                     f"score {application.score} → {application.status}", conn=conn)
    if application.status == "Pre-Approved":
        email_service.send_adoption_decision(applicant.email, applicant.name, application.application_id,
                                             animal["name"], "Pre-Approved")
    return application


def list_applications(applicant: User | None = None) -> pd.DataFrame:
    df = dh.load_table("adoption_applications")
    return df if applicant is None else df[df["applicant_id"] == applicant.user_id]


def review_application(admin: User, application_id: str, decision: str) -> AdoptionApplication:
    _require(admin, "review_applications")
    if decision not in {"Approved", "Rejected"}:
        raise ValidationError("Decision must be Approved or Rejected.")
    row = dh.find_row("adoption_applications", "application_id", application_id)
    if row is None:
        raise NotFound("Application not found.")
    application = AdoptionApplication.from_dict(row)
    if not application.is_pending:
        raise Conflict(f"This application is already {application.status}.")
    stamp, pending = now_str(), ["Pre-Approved", "Under Review"]
    reviewed = {"reviewed_by": admin.user_id, "reviewed_at": stamp}
    # Decision, animal status and closing the other applications: all or nothing.
    with dh.transaction() as conn:
        if not dh.update_row("adoption_applications", "application_id", application_id,
                             {"status": decision, **reviewed}, conn=conn, expected={"status": pending}):
            raise Conflict("Another admin reviewed this application just now.")
        if decision == "Approved":
            if not dh.update_row("animals", "animal_id", application.animal_id, {"status": "Adopted"},
                                 conn=conn, expected={"status": "Available"}):
                raise Conflict("This animal has already been adopted.")
            others = dh.load_table("adoption_applications", conn=conn)
            others = others[(others["animal_id"] == application.animal_id) & others["status"].isin(pending)]
            for other_id in others["application_id"]:
                dh.update_row("adoption_applications", "application_id", other_id,
                              {"status": "Closed", **reviewed}, conn=conn)
        dh.log_event(admin.user_id, admin.role, "ADOPTION_" + decision.upper(),
                     f"{application_id} ({application.applicant_name}) for {application.animal_id}", conn=conn)
    applicant = get_user(application.applicant_id)
    if applicant:      # only tell the applicant once the decision is safely saved
        animal = dh.find_row("animals", "animal_id", application.animal_id) or {}
        email_service.send_adoption_decision(applicant.email, applicant.name, application_id,
                                             animal.get("name", application.animal_id), decision)
    application.status = decision
    return application


def add_animal(admin: User, name: str, species: str, breed: str, age_years, gender: str,
               vaccinated: bool, sterilized: bool, temperament: str, description: str,
               case_id: str = "") -> Animal:
    _require(admin, "manage_animals")
    if not v.is_valid("name", name):
        raise ValidationError("Give the animal a name (letters only).")
    if species not in ANIMAL_TYPES:
        raise ValidationError("Choose a species.")
    try:
        age = float(age_years)
    except (TypeError, ValueError):
        raise ValidationError("Age must be a number of years.") from None
    if not 0 <= age <= 40:
        raise ValidationError("Age must be between 0 and 40 years.")
    if case_id:
        load_case(case_id)
    with dh.transaction() as conn:
        animal = Animal(
            animal_id=dh.next_id("animals", "A", 3, conn=conn), name=v.sanitize_text(name, 40),
            species=species, breed=v.sanitize_text(breed, 40) or "Indie", age_years=f"{age:g}",
            gender=gender, vaccinated="yes" if vaccinated else "no",
            sterilized="yes" if sterilized else "no", temperament=v.sanitize_text(temperament, 60),
            description=v.sanitize_text(description, 300), case_id=case_id,
        )
        dh.append_row("animals", animal.to_dict(), conn=conn)
        dh.log_event(admin.user_id, admin.role, "ANIMAL_ADDED",
                     f"{animal.animal_id} {animal.name} listed for adoption", conn=conn)
    return animal


def list_animals(only_available: bool = False) -> pd.DataFrame:
    return available_animals() if only_available else dh.load_table("animals")


# ======================================================================= inventory / offline import
def list_inventory() -> pd.DataFrame:
    return dh.load_table("inventory")


def export_table(admin: User, name: str, kind: str = "csv") -> bytes:
    _require(admin, "export_data")
    if name not in dh.SCHEMAS:
        raise NotFound(f"Unknown table {name}.")
    return dh.table_to_csv_bytes(name) if kind == "csv" else dh.table_to_xml_bytes(name)


def save_inventory(admin: User, df: pd.DataFrame) -> int:
    _require(admin, "manage_inventory")
    clean = df.copy()
    if "item_id" not in clean:
        clean["item_id"] = ""
    for column in ("quantity", "reorder_level"):
        numbers = pd.to_numeric(clean[column], errors="coerce")
        if numbers.isna().any() or (numbers < 0).any():
            raise ValidationError(f"Every {column.replace('_', ' ')} must be a number of 0 or more.")
        clean[column] = numbers.astype(int).astype(str)
    clean["item"] = clean["item"].map(lambda s: v.sanitize_text(str(s), 60))
    if (clean["item"] == "").any():
        raise ValidationError("Every item needs a name.")
    missing_id = clean["item_id"].astype(str).str.strip().isin(["", "nan", "None"])
    if missing_id.any():
        start = int(dh.next_id("inventory", "", 0) or 1)
        clean.loc[missing_id, "item_id"] = [f"INV-{start + i:03d}" for i in range(missing_id.sum())]
    if clean["item_id"].duplicated().any():
        raise ValidationError("Two rows have the same item id.")
    clean["updated_at"] = now_str()
    with dh.transaction() as conn:
        dh.save_table("inventory", clean, conn=conn)
        dh.log_event(admin.user_id, admin.role, "INVENTORY_UPDATED", f"{len(clean)} items saved", conn=conn)
    return len(clean)


def import_offline_cases(admin: User, source) -> tuple[int, list[str]]:
    """
    Import rescue cases recorded offline (CSV file from a field phone/register).
    Needs columns animal_type, injury_level, description, pincode; address optional.
    Returns (imported count, list of skipped-row messages).
    """
    _require(admin, "assign_case")
    df = pd.read_csv(source, dtype=str, keep_default_na=False)
    required = {"animal_type", "injury_level", "description", "pincode"}
    missing = required - set(df.columns)
    if missing:
        raise ValidationError("The file is missing columns: " + ", ".join(sorted(missing)))
    imported, skipped = 0, []
    for number, row in enumerate(df.to_dict(orient="records"), start=2):
        try:
            create_rescue_case(admin, row["animal_type"].strip().title(),
                               row["injury_level"].strip().title(), row["description"],
                               row["pincode"], row.get("address", ""), use_network=False)
            imported += 1
        except ValidationError as error:
            skipped.append(f"Row {number}: {'; '.join(error.problems)}")
    dh.log_event(admin.user_id, admin.role, "OFFLINE_IMPORT",
                 f"{imported} cases imported, {len(skipped)} skipped")
    return imported, skipped


# ======================================================================= read-only helpers for the API
def list_allocations() -> pd.DataFrame:
    return dh.load_table("allocations")


def funds_overview() -> pd.DataFrame:
    from analytics.pandas_engine import funds_overview as overview
    return overview(dh.load_table("donations"), dh.load_table("allocations"))


def case_funding() -> pd.DataFrame:
    from analytics.pandas_engine import case_funding_table
    return case_funding_table(dh.load_table("rescue_cases"), dh.load_table("donations"),
                              dh.load_table("allocations"))


def audit_log(admin: User) -> pd.DataFrame:
    _require(admin, "view_audit_log")
    return dh.read_audit_log()


def audit_log_xml(admin: User) -> bytes:
    _require(admin, "view_audit_log")
    return dh.audit_log_bytes()


def any_table(admin: User, name: str) -> pd.DataFrame:
    """Any table for the admin's data-quality tools (never the password hashes)."""
    _require(admin, "export_data")
    if name not in dh.SCHEMAS:
        raise NotFound(f"Unknown table {name}.")
    df = dh.load_table(name)
    return df.drop(columns=["password_hash"]) if name == "users" else df


def create_backup(admin: User) -> list[Path]:
    _require(admin, "export_data")
    written = dh.export_backup()
    dh.log_event(admin.user_id, admin.role, "BACKUP_CREATED", f"{len(written)} files in {written[0].parent.name}")
    return written


# ======================================================================= e-mail settings (admin)
def email_status(admin: User) -> dict:
    """Is real e-mail switched on, and what happened to the last e-mails? (never shows the password)"""
    import json
    import config
    _require(admin, "manage_users")
    recent = []
    if config.OUTBOX_LOG.exists():
        for line in config.OUTBOX_LOG.read_text(encoding="utf-8").splitlines()[-15:][::-1]:
            try:
                recent.append(json.loads(line))
            except ValueError:
                continue
    return {"enabled": config.EMAIL_ENABLED, "host": config.SMTP_HOST, "port": config.SMTP_PORT,
            "user": config.SMTP_USER, "sender": config.SMTP_FROM if config.EMAIL_ENABLED else "",
            "password_set": bool(config.SMTP_PASSWORD), "recent": recent}


def send_test_email(admin: User, to: str) -> dict:
    _require(admin, "manage_users")
    to = v.normalize("email", to)
    if not v.is_valid("email", to):
        raise ValidationError(v.MESSAGES["email"])
    subject, text, html_body = email_service.welcome_email(admin.name, "Test")
    result = email_service.send_email(to, "PawConnect test e-mail", text, html_body)
    dh.log_event(admin.user_id, admin.role, "EMAIL_TEST", f"Test e-mail to {v.mask_email(to)}: {result['status']}")
    return result
