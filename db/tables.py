"""
Table definitions (SQLAlchemy Core). One table per old CSV file, plus
audit_events, which replaces data/audit_logs.xml.

Constraints the database now enforces for us:
  * primary keys and foreign keys (a donation must belong to a real user, an
    allocation to a real case, ...);
  * UNIQUE e-mail and mobile number;
  * CHECK constraints for every status / level / role list in config.py;
  * NOT NULL on the columns a record can't do without;
  * indexes on the columns we filter by most (case status, pincode, donation time).

Money is stored as whole paise in a BIGINT column (₹12.50 → 1250), never as a
float, so sums are always exact. The `Money` type converts for us: Python code
reads and writes `Decimal("12.50")`, the database holds 1250.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import (BigInteger, CheckConstraint, Column, DateTime, Float, ForeignKey,
                        Index, Integer, MetaData, String, Table, Text, TypeDecorator)

from config import (ALLOCATABLE_FUNDS, ALLOCATION_PURPOSES, ANIMAL_STATUSES, ANIMAL_TYPES,
                    APPLICATION_STATUSES, CASE_STATUSES, CONTRIBUTION_TYPES, DONATION_STATUSES,
                    INJURY_LEVELS, PAYMENT_METHODS, ROLES)

# Stable constraint names make Alembic migrations predictable on every database.
metadata = MetaData(naming_convention={
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
})

PAISE = Decimal("0.01")


class Money(TypeDecorator):
    """Rupees in Python (Decimal), integer paise in the database."""
    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            return None
        rupees = Decimal(str(value)).quantize(PAISE, rounding=ROUND_HALF_UP)
        return int(rupees * 100)

    def process_result_value(self, value, dialect):
        return None if value is None else (Decimal(int(value)) / 100).quantize(PAISE)


def one_of(column: str, values: list[str]) -> str:
    """SQL text for  column IN ('a', 'b', ...)  used in CHECK constraints."""
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return f"{column} IN ({quoted})"


YES_NO = ["yes", "no"]

users = Table(
    "users", metadata,
    Column("user_id", String(10), primary_key=True),
    Column("name", String(60), nullable=False),
    Column("email", String(120), nullable=False, unique=True),
    Column("mobile", String(10), unique=True),      # optional; still unique when given (NULLs may repeat)
    Column("role", String(10), nullable=False),
    Column("pincode", String(6), nullable=False),
    Column("password_hash", String(200), nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("verified", String(3), nullable=False, server_default="yes"),
    CheckConstraint(one_of("role", ROLES), name="role"),
    CheckConstraint(one_of("verified", YES_NO), name="verified"),
)

rescue_cases = Table(
    "rescue_cases", metadata,
    Column("case_id", String(12), primary_key=True),
    Column("reporter_id", String(10), ForeignKey("users.user_id"), nullable=False),
    Column("animal_type", String(10), nullable=False),
    Column("injury_level", String(10), nullable=False),
    Column("description", Text, nullable=False),
    Column("pincode", String(6), nullable=False, index=True),
    Column("address", String(150)),
    Column("latitude", Float),
    Column("longitude", Float),
    Column("location_source", String(40)),
    Column("photo_path", String(255)),
    Column("status", String(25), nullable=False, server_default="Reported", index=True),
    Column("rescuer_id", String(10), ForeignKey("users.user_id")),
    Column("reported_at", DateTime, nullable=False),
    Column("assigned_at", DateTime),
    Column("updated_at", DateTime, nullable=False),
    Column("medical_notes", Text),
    Column("estimated_cost", Money),
    CheckConstraint(one_of("status", CASE_STATUSES), name="status"),
    CheckConstraint(one_of("injury_level", INJURY_LEVELS), name="injury_level"),
    CheckConstraint(one_of("animal_type", ANIMAL_TYPES), name="animal_type"),
    CheckConstraint("estimated_cost IS NULL OR estimated_cost >= 0", name="cost_not_negative"),
    # Once a case leaves 'Reported' somebody must be responsible for it.
    CheckConstraint("status = 'Reported' OR rescuer_id IS NOT NULL", name="rescuer_when_assigned"),
)

donations = Table(
    "donations", metadata,
    Column("transaction_id", String(30), primary_key=True),
    Column("donor_id", String(10), ForeignKey("users.user_id"), nullable=False, index=True),
    Column("donor_name", String(60), nullable=False),
    Column("donor_email", String(120)),
    Column("amount", Money, nullable=False),
    Column("contribution_type", String(30), nullable=False),
    Column("case_id", String(12), ForeignKey("rescue_cases.case_id")),
    Column("method", String(10), nullable=False),
    Column("payment_ref", String(60), index=True),       # gateway payment / order id
    Column("masked_account", String(60)),
    Column("status", String(10), nullable=False),
    Column("timestamp", DateTime, nullable=False, index=True),
    CheckConstraint("amount > 0", name="amount_positive"),
    CheckConstraint(one_of("contribution_type", CONTRIBUTION_TYPES), name="contribution_type"),
    CheckConstraint(one_of("method", PAYMENT_METHODS), name="method"),
    CheckConstraint(one_of("status", DONATION_STATUSES), name="status"),
    CheckConstraint("contribution_type <> 'Specific Medical Case' OR case_id IS NOT NULL",
                    name="case_for_specific"),
)

allocations = Table(
    "allocations", metadata,
    Column("allocation_id", String(12), primary_key=True),
    Column("case_id", String(12), ForeignKey("rescue_cases.case_id"), nullable=False, index=True),
    Column("source_fund", String(30), nullable=False),
    Column("amount", Money, nullable=False),
    Column("purpose", String(30), nullable=False),
    Column("allocated_by", String(10), ForeignKey("users.user_id"), nullable=False),
    Column("allocated_at", DateTime, nullable=False),
    Column("notes", String(200)),
    CheckConstraint("amount > 0", name="amount_positive"),
    CheckConstraint(one_of("source_fund", ALLOCATABLE_FUNDS), name="source_fund"),
    CheckConstraint(one_of("purpose", ALLOCATION_PURPOSES), name="purpose"),
)

animals = Table(
    "animals", metadata,
    Column("animal_id", String(10), primary_key=True),
    Column("name", String(40), nullable=False),
    Column("species", String(10), nullable=False),
    Column("breed", String(40)),
    Column("age_years", Float),
    Column("gender", String(10)),
    Column("vaccinated", String(3), nullable=False, server_default="no"),
    Column("sterilized", String(3), nullable=False, server_default="no"),
    Column("temperament", String(60)),
    Column("description", String(300)),
    Column("photo_path", String(255)),
    Column("status", String(10), nullable=False, server_default="Available", index=True),
    Column("case_id", String(12), ForeignKey("rescue_cases.case_id")),
    Column("added_at", DateTime, nullable=False),
    CheckConstraint(one_of("species", ANIMAL_TYPES), name="species"),
    CheckConstraint(one_of("status", ANIMAL_STATUSES), name="status"),
    CheckConstraint(one_of("vaccinated", YES_NO), name="vaccinated"),
    CheckConstraint(one_of("sterilized", YES_NO), name="sterilized"),
    CheckConstraint("age_years IS NULL OR (age_years >= 0 AND age_years <= 40)", name="age"),
)

adoption_applications = Table(
    "adoption_applications", metadata,
    Column("application_id", String(12), primary_key=True),
    Column("applicant_id", String(10), ForeignKey("users.user_id"), nullable=False, index=True),
    Column("applicant_name", String(60), nullable=False),
    Column("animal_id", String(10), ForeignKey("animals.animal_id"), nullable=False, index=True),
    Column("housing", String(60), nullable=False),
    Column("experience", String(60), nullable=False),
    Column("hours_alone", String(60), nullable=False),
    Column("family", String(60), nullable=False),
    Column("budget", String(60), nullable=False),
    Column("reason", String(400)),
    Column("score", Integer, nullable=False),
    Column("status", String(15), nullable=False),
    Column("submitted_at", DateTime, nullable=False),
    Column("reviewed_by", String(10), ForeignKey("users.user_id")),
    Column("reviewed_at", DateTime),
    CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
    CheckConstraint(one_of("status", APPLICATION_STATUSES), name="status"),
)

inventory = Table(
    "inventory", metadata,
    Column("item_id", String(10), primary_key=True),
    Column("item", String(60), nullable=False),
    Column("category", String(30)),
    Column("quantity", Integer, nullable=False),
    Column("unit", String(20)),
    Column("reorder_level", Integer, nullable=False, server_default="0"),
    Column("updated_at", DateTime, nullable=False),
    CheckConstraint("quantity >= 0", name="quantity_not_negative"),
    CheckConstraint("reorder_level >= 0", name="reorder_not_negative"),
)

audit_events = Table(
    "audit_events", metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),   # shown as EV-00001
    Column("timestamp", DateTime, nullable=False, index=True),
    # Not a foreign key on purpose: failed logins record what was typed, and
    # "system" events have no user at all.
    Column("actor", String(60), nullable=False),
    Column("role", String(10), nullable=False),
    Column("action", String(30), nullable=False, index=True),
    Column("details", Text),
)

TABLES: dict[str, Table] = {t.name: t for t in (users, rescue_cases, donations, allocations, animals,
                                                adoption_applications, inventory)}
# Order to delete in so foreign keys are never broken (children first).
DELETE_ORDER = ["audit_events", "adoption_applications", "allocations", "donations", "animals",
                "rescue_cases", "inventory", "users"]

# Composite index for the rescuer queue: "Reported cases in my area".
Index("ix_rescue_cases_status_pincode", rescue_cases.c.status, rescue_cases.c.pincode)
