"""
Object-oriented domain model (Unit 1: OOP, inheritance, `abc`).

User hierarchy
    User (abstract)
     ├── Citizen
     │    └── Adopter        (a citizen who also tracks adoption applications)
     ├── Rescuer
     ├── Donor
     └── Admin              (has every permission)

Entities: RescueCase, DonationTransaction, FundAllocation, Animal, AdoptionApplication.
Records travel between the database layer and the UIs as dicts of text, so each
class has to_dict() / from_dict().
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from decimal import Decimal

from config import (CASE_STATUSES, DEFAULT_TREATMENT_COST, PASSWORD_ITERATIONS,
                    PREAPPROVAL_THRESHOLD)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ======================================================================= passwords
def hash_password(password: str, salt: str | None = None,
                  iterations: int = PASSWORD_ITERATIONS) -> str:
    """PBKDF2-SHA256 hash stored as 'iterations$salt$digest'. Plain passwords are never saved."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations)
    return f"{iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        iterations, salt, digest = stored.split("$")
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt),
                                    int(iterations)).hex()
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(check, digest)


# ======================================================================= users
class User(ABC):
    """Base class for every account. Sub-classes define role, permissions and dashboard."""

    role = "User"

    def __init__(self, user_id: str, name: str, email: str, mobile: str, pincode: str,
                 password_hash: str = "", created_at: str | None = None, verified: str = "yes"):
        self.user_id = user_id
        self.name = name
        self.email = email
        self.mobile = mobile
        self.pincode = pincode
        self.password_hash = password_hash
        self.created_at = created_at or now_str()
        self.verified = verified

    # ---- abstract interface (each role must implement these)
    @property
    @abstractmethod
    def permissions(self) -> set[str]:
        """What this role is allowed to do."""

    @property
    @abstractmethod
    def dashboard_title(self) -> str:
        """Heading of the role's dashboard."""

    # ---- shared behaviour
    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def check_password(self, password: str) -> bool:
        return verify_password(password, self.password_hash)

    def set_password(self, password: str) -> None:
        self.password_hash = hash_password(password)

    @property
    def first_name(self) -> str:
        return self.name.split()[0] if self.name else ""

    @property
    def area_code(self) -> str:
        """First 3 digits of the pincode = the postal sorting district (used for rescue areas)."""
        return str(self.pincode)[:3]

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id, "name": self.name, "email": self.email,
            "mobile": self.mobile, "role": self.role, "pincode": self.pincode,
            "password_hash": self.password_hash, "created_at": self.created_at,
            "verified": self.verified,
        }

    def public_dict(self) -> dict:
        """Safe to show on screen or keep in a session – no password hash."""
        data = self.to_dict()
        data.pop("password_hash")
        return data

    @staticmethod
    def from_dict(data: dict) -> "User":
        cls = USER_CLASSES.get(data.get("role", ""))
        if cls is None:
            raise ValueError(f"Unknown role: {data.get('role')!r}")
        return cls(
            user_id=data["user_id"], name=data["name"], email=data["email"],
            mobile=str(data["mobile"]), pincode=str(data["pincode"]),
            password_hash=data.get("password_hash", ""), created_at=data.get("created_at"),
            verified=data.get("verified", "yes"),
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.user_id!r}, {self.name!r})"


class Citizen(User):
    role = "Citizen"

    @property
    def permissions(self) -> set[str]:
        return {"report_sos", "view_own_reports", "browse_adoption", "apply_adoption"}

    @property
    def dashboard_title(self) -> str:
        return "Citizen dashboard"


class Adopter(Citizen):
    """An adopter can do everything a citizen can, plus track applications."""
    role = "Adopter"

    @property
    def permissions(self) -> set[str]:
        return super().permissions | {"track_applications"}

    @property
    def dashboard_title(self) -> str:
        return "Adopter dashboard"


class Rescuer(User):
    role = "Rescuer"

    @property
    def permissions(self) -> set[str]:
        return {"view_cases", "accept_case", "update_case", "add_medical_note"}

    @property
    def dashboard_title(self) -> str:
        return "Field rescuer dashboard"


class Donor(User):
    role = "Donor"

    @property
    def permissions(self) -> set[str]:
        return {"donate", "view_own_donations", "view_transparency"}

    @property
    def dashboard_title(self) -> str:
        return "Donor portal"


class Admin(User):
    role = "Admin"

    @property
    def permissions(self) -> set[str]:
        everyone = set().union(*(cls(*[""] * 5).permissions
                                 for cls in (Citizen, Adopter, Rescuer, Donor)))
        return everyone | {"assign_case", "allocate_funds", "review_applications",
                           "manage_animals", "manage_inventory", "manage_users", "export_data",
                           "view_audit_log"}

    @property
    def dashboard_title(self) -> str:
        return "Shelter administration"


USER_CLASSES: dict[str, type[User]] = {
    cls.role: cls for cls in (Citizen, Adopter, Rescuer, Donor, Admin)
}


# ======================================================================= helpers
class CsvRecord:
    """Mixin for dataclasses that are stored as one table row (once a CSV row – hence the name)."""

    def to_dict(self) -> dict:
        return {k: ("" if v is None else str(v)) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, data: dict):
        names = {f.name for f in fields(cls)}
        return cls(**{k: ("" if v is None else str(v)) for k, v in data.items() if k in names})


# ======================================================================= rescue cases
@dataclass
class RescueCase(CsvRecord):
    case_id: str
    reporter_id: str
    animal_type: str
    injury_level: str
    description: str
    pincode: str
    address: str = ""
    latitude: str = ""
    longitude: str = ""
    location_source: str = ""
    photo_path: str = ""
    status: str = "Reported"
    rescuer_id: str = ""
    reported_at: str = field(default_factory=now_str)
    assigned_at: str = ""
    updated_at: str = field(default_factory=now_str)
    medical_notes: str = ""
    estimated_cost: str = ""

    def __post_init__(self):
        if not self.estimated_cost:
            self.estimated_cost = str(DEFAULT_TREATMENT_COST.get(self.injury_level, 3000))

    @property
    def priority(self) -> int:
        """3 = critical, 1 = low. Used to sort the rescuer queue."""
        return {"Critical": 3, "Moderate": 2, "Low": 1}.get(self.injury_level, 0)

    @property
    def is_open(self) -> bool:
        return self.status != "Recovered"

    @property
    def progress(self) -> float:
        return CASE_STATUSES.index(self.status) / (len(CASE_STATUSES) - 1)

    def next_status(self) -> str | None:
        index = CASE_STATUSES.index(self.status)
        return CASE_STATUSES[index + 1] if index + 1 < len(CASE_STATUSES) else None

    def advance(self, rescuer_id: str | None = None) -> str:
        """Move to the next status. Moving to 'Assigned' needs a rescuer."""
        new_status = self.next_status()
        if new_status is None:
            raise ValueError(f"{self.case_id} is already {self.status}.")
        if new_status == "Assigned":
            if not (rescuer_id or self.rescuer_id):
                raise ValueError("A rescuer must accept the case before it is assigned.")
            self.rescuer_id = rescuer_id or self.rescuer_id
            self.assigned_at = now_str()
        self.status = new_status
        self.updated_at = now_str()
        return new_status

    def add_note(self, note: str, author: str) -> None:
        entry = f"[{now_str()}] {author}: {note}"
        self.medical_notes = f"{self.medical_notes} | {entry}" if self.medical_notes else entry
        self.updated_at = now_str()

    def notes_list(self) -> list[str]:
        return [n.strip() for n in self.medical_notes.split(" | ") if n.strip()]


# ======================================================================= money
@dataclass
class DonationTransaction(CsvRecord):
    transaction_id: str
    donor_id: str
    donor_name: str
    donor_email: str
    amount: Decimal
    contribution_type: str
    case_id: str = ""
    method: str = ""
    payment_ref: str = ""
    masked_account: str = ""
    status: str = "Pending"
    timestamp: str = field(default_factory=now_str)

    @staticmethod
    def new_id() -> str:
        """Unique reference like PC-DON-20261027-7F3A9C."""
        return f"PC-DON-{datetime.now():%Y%m%d}-{secrets.token_hex(3).upper()}"

    @property
    def succeeded(self) -> bool:
        return self.status == "Success"

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["amount"] = f"{Decimal(str(self.amount)):.2f}"     # exact – never via float
        return data


@dataclass
class FundAllocation(CsvRecord):
    allocation_id: str
    case_id: str
    source_fund: str
    amount: Decimal
    purpose: str
    allocated_by: str
    allocated_at: str = field(default_factory=now_str)
    notes: str = ""

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["amount"] = f"{Decimal(str(self.amount)):.2f}"     # exact – never via float
        return data


# ======================================================================= adoption
@dataclass
class Animal(CsvRecord):
    animal_id: str
    name: str
    species: str
    breed: str = "Indie"
    age_years: str = "1"
    gender: str = "Unknown"
    vaccinated: str = "no"
    sterilized: str = "no"
    temperament: str = ""
    description: str = ""
    photo_path: str = ""
    status: str = "Available"
    case_id: str = ""
    added_at: str = field(default_factory=now_str)

    @property
    def emoji(self) -> str:
        return {"Dog": "🐕", "Cat": "🐈", "Cow": "🐄", "Bird": "🐦", "Monkey": "🐒"}.get(
            self.species, "🐾")


# Each answer is worth some points; the maximum adds up to exactly 100.
QUESTIONNAIRE: dict[str, dict] = {
    "housing": {
        "question": "Where will the pet live?",
        "options": {"Own house with a yard or terrace": 25, "Own house or flat": 20,
                    "Rented home where pets are allowed": 15, "Rented home, not sure about pets": 5},
    },
    "experience": {
        "question": "Your experience with pets",
        "options": {"I have pets now": 20, "I had pets before": 15,
                    "First pet, but I've read up and asked a vet": 10, "No experience": 3},
    },
    "hours_alone": {
        "question": "How many hours a day would the pet be alone?",
        "options": {"Less than 4 hours": 20, "4 to 8 hours": 12, "More than 8 hours": 4},
    },
    "family": {
        "question": "Does everyone at home agree to the adoption?",
        "options": {"Yes, everyone agrees": 15, "Most people agree": 8, "Haven't discussed it": 0},
    },
    "budget": {
        "question": "Monthly budget for food and vet care",
        "options": {"₹2,000 or more": 20, "₹1,000 – ₹2,000": 12, "Less than ₹1,000": 5},
    },
}
MAX_SCORE = sum(max(q["options"].values()) for q in QUESTIONNAIRE.values())   # = 100


def score_answers(answers: dict[str, str]) -> int:
    """Add up the points for each answer. Missing or unknown answers score 0."""
    return sum(QUESTIONNAIRE[key]["options"].get(answers.get(key, ""), 0)
               for key in QUESTIONNAIRE)


@dataclass
class AdoptionApplication(CsvRecord):
    application_id: str
    applicant_id: str
    applicant_name: str
    animal_id: str
    housing: str
    experience: str
    hours_alone: str
    family: str
    budget: str
    reason: str = ""
    score: str = ""
    status: str = ""
    submitted_at: str = field(default_factory=now_str)
    reviewed_by: str = ""
    reviewed_at: str = ""

    def __post_init__(self):
        if self.score == "":
            self.evaluate()

    @property
    def answers(self) -> dict[str, str]:
        return {key: getattr(self, key) for key in QUESTIONNAIRE}

    def evaluate(self) -> int:
        """Score the questionnaire and auto-flag applications at or above the threshold."""
        points = score_answers(self.answers)
        self.score = str(points)
        if not self.status:
            self.status = "Pre-Approved" if points >= PREAPPROVAL_THRESHOLD else "Under Review"
        return points

    @property
    def is_pending(self) -> bool:
        return self.status in {"Pre-Approved", "Under Review"}
