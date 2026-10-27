"""
Regular-expression validation (Unit 1: `re`).

Every form in the web app and the desktop console goes through these helpers,
so the rules live in exactly one place.
"""
import re
from datetime import date

# Patterns from the project plan, compiled once.
PATTERNS = {
    "mobile": re.compile(r"^[6-9]\d{9}$"),
    "email": re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"),
    "upi": re.compile(r"^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$"),
    "pincode": re.compile(r"^[1-9][0-9]{5}$"),
    # extra rules used by the forms
    "name": re.compile(r"^[A-Za-z][A-Za-z .'-]{1,59}$"),
    "card": re.compile(r"^\d{16}$"),
    "expiry": re.compile(r"^(0[1-9]|1[0-2])/(\d{2})$"),
    "cvv": re.compile(r"^\d{3}$"),
    "amount": re.compile(r"^\d{1,7}(\.\d{1,2})?$"),
    "otp": re.compile(r"^\d{6}$"),
}

PASSWORD_RULES = [
    (re.compile(r".{8,}"), "at least 8 characters"),
    (re.compile(r"[A-Z]"), "one capital letter"),
    (re.compile(r"[a-z]"), "one small letter"),
    (re.compile(r"\d"), "one number"),
    (re.compile(r"[^A-Za-z0-9]"), "one symbol such as @ or #"),
]

MESSAGES = {
    "mobile": "Enter a valid 10-digit Indian mobile number starting with 6, 7, 8 or 9.",
    "email": "Enter a valid e-mail address, for example name@example.com.",
    "upi": "Enter a valid UPI ID, for example yourname@okaxis.",
    "pincode": "Enter a valid 6-digit pincode (it can't start with 0).",
    "name": "Use letters, spaces, dots, apostrophes or hyphens only (2–60 characters).",
    "card": "Card number must be 16 digits.",
    "expiry": "Expiry must be in MM/YY format.",
    "cvv": "CVV must be 3 digits.",
    "amount": "Enter an amount in rupees, up to 2 decimal places.",
    "otp": "The OTP is 6 digits.",
}


def normalize(kind: str, value) -> str:
    """Trim the value and remove the spaces people commonly type."""
    text = "" if value is None else str(value).strip()
    if kind in {"mobile", "card", "pincode", "cvv", "otp"}:
        text = re.sub(r"[\s-]", "", text)
        if kind == "mobile":
            text = re.sub(r"^(\+91|91|0)(?=[6-9]\d{9}$)", "", text)
    if kind in {"email", "upi"}:
        text = text.lower()
    return text


def is_valid(kind: str, value) -> bool:
    """True when `value` matches the regex for `kind`."""
    return bool(PATTERNS[kind].fullmatch(normalize(kind, value)))


def validate(kind: str, value) -> tuple[bool, str]:
    """Return (ok, message). The message is empty when the value is valid."""
    if is_valid(kind, value):
        return True, ""
    return False, MESSAGES.get(kind, f"Invalid {kind}.")


def password_problems(password: str) -> list[str]:
    """List the password rules that are not met (empty list = strong enough)."""
    return [text for pattern, text in PASSWORD_RULES if not pattern.search(password or "")]


def luhn_check(number: str) -> bool:
    """Luhn checksum used by every real card number."""
    digits = [int(d) for d in normalize("card", number) if d.isdigit()]
    if not digits:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def card_brand(number: str) -> str:
    number = normalize("card", number)
    if re.match(r"^4", number):
        return "Visa"
    if re.match(r"^(5[1-5]|2[2-7])", number):
        return "Mastercard"
    if re.match(r"^(60|65|81|82|508)", number):
        return "RuPay"
    return "Card"


def expiry_ok(expiry: str, today: date | None = None) -> bool:
    """MM/YY that is this month or later."""
    match = PATTERNS["expiry"].fullmatch((expiry or "").strip())
    if not match:
        return False
    today = today or date.today()
    month, year = int(match.group(1)), 2000 + int(match.group(2))
    return (year, month) >= (today.year, today.month)


def mask_card(number: str) -> str:
    number = normalize("card", number)
    return f"{card_brand(number)} •••• {number[-4:]}" if len(number) >= 4 else "••••"


def mask_upi(upi: str) -> str:
    upi = normalize("upi", upi)
    if "@" not in upi:
        return "••••"
    handle, bank = upi.split("@", 1)
    visible = handle[:2]
    return f"{visible}{'•' * max(len(handle) - 2, 2)}@{bank}"


def mask_email(email: str) -> str:
    """riya@gmail.com → r•••@gmail.com (shown when we say where the OTP went)."""
    email = normalize("email", email)
    if "@" not in email:
        return "•••"
    name, domain = email.split("@", 1)
    return f"{name[:1]}•••@{domain}"


def mask_mobile(mobile: str) -> str:
    mobile = normalize("mobile", mobile)
    return f"{mobile[:2]}••••••{mobile[-2:]}" if len(mobile) == 10 else mobile


_TAGS = re.compile(r"<[^>]*>")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str, max_len: int = 500) -> str:
    """Strip HTML tags and control characters from free text, collapse whitespace."""
    text = _CONTROL.sub("", _TAGS.sub("", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    # CSV injection guard: a cell starting with = + - @ can run formulas in Excel.
    if text[:1] in {"=", "+", "-", "@"}:
        text = "'" + text
    return text[:max_len]


def safe_filename(name: str) -> str:
    """Keep only safe characters in an uploaded file name."""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name or "file")
    return re.sub(r"_+", "_", name).strip("._") or "file"
