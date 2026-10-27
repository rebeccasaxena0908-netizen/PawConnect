"""
Realistic demo data for six months of PawConnect activity around Delhi NCR.

Run `python main.py --reset-data` to start again from this data.
Everything is written in ONE database transaction, so a half-seeded database
can't happen.
A few cells are left empty on purpose (anonymous donors' e-mails, cases with no
notes yet) so the missing-value cleaning in pandas_engine has something to do.
"""
from __future__ import annotations

import random
import shutil
from datetime import datetime, timedelta

from analytics import data_handler as dh
from config import CASE_STATUSES, DATABASE_URL, DEFAULT_TREATMENT_COST, OUTBOX_LOG, UPLOAD_DIR
from core import validators as v
from core.models import (AdoptionApplication, Animal, QUESTIONNAIRE, RescueCase, hash_password)
from services.api_service import offline_location

DEMO_ACCOUNTS = [
    # (id, name, email, mobile, role, pincode, password)
    ("U0001", "Meera Kapoor", "admin@pawconnect.org", "9810000001", "Admin", "201001", "Admin@123"),
    ("U0002", "Arjun Singh", "arjun.rescue@pawconnect.org", "9810000002", "Rescuer", "201001", "Rescuer@123"),
    ("U0003", "Fatima Khan", "fatima.rescue@pawconnect.org", "9810000003", "Rescuer", "110001", "Rescuer@123"),
    ("U0004", "Rohit Verma", "rohit.rescue@pawconnect.org", "9810000004", "Rescuer", "201301", "Rescuer@123"),
    ("U0005", "Ananya Sharma", "ananya@example.com", "9810000005", "Donor", "110017", "Donor@123"),
    ("U0006", "Vikram Mehta", "vikram@example.com", "9810000006", "Donor", "122001", "Donor@123"),
    ("U0007", "GreenLeaf Foods Pvt Ltd", "csr@greenleaf.example.com", "9810000007", "Donor", "201301", "Donor@123"),
    ("U0008", "Sneha Iyer", "sneha@example.com", "9810000008", "Donor", "201002", "Donor@123"),
    ("U0009", "Karan Malhotra", "karan@example.com", "9810000009", "Citizen", "201001", "Citizen@123"),
    ("U0010", "Pooja Yadav", "pooja@example.com", "9810000010", "Citizen", "110001", "Citizen@123"),
    ("U0011", "Imran Qureshi", "imran@example.com", "9810000011", "Citizen", "201301", "Citizen@123"),
    ("U0012", "Riya Bansal", "riya@example.com", "9810000012", "Adopter", "201010", "Adopter@123"),
    ("U0013", "Aditya Rao", "aditya@example.com", "9810000013", "Adopter", "110092", "Adopter@123"),
]
AREA_PINCODES = ["201001", "201002", "201010", "201014", "110001", "110017", "110092",
                 "201301", "201304", "122001"]
DESCRIPTIONS = {
    "Dog": ["Limping badly, back leg looks broken", "Hit by a car near the market, bleeding",
            "Deep wound on neck, maggots visible", "Puppy with a skin infection, losing fur",
            "Very weak and not eating for two days", "Eye injury, keeps it shut"],
    "Cat": ["Kitten stuck in a drain, crying", "Cat with a burnt paw near the bakery",
            "Mother cat with an injured tail", "Cat breathing heavily, mouth open"],
    "Cow": ["Cow with plastic stuck in mouth", "Cow with a deep cut on its leg near the highway"],
    "Bird": ["Pigeon tangled in kite string (manjha)", "Kite with an injured wing on the terrace"],
    "Monkey": ["Monkey electrocuted on wires, burns on arms"],
}
NOTES = ["Wound cleaned and dressed", "X-ray done, hairline fracture", "Started antibiotics",
         "Fluids given, eating again", "Stitches removed", "Vaccinated against rabies",
         "Sterilised during treatment", "Ready for release / adoption"]
ANIMALS = [
    ("Bruno", "Dog", "Indie", 2, "Male", "Playful, loves fetch"),
    ("Sheru", "Dog", "Indie", 4, "Male", "Calm and loyal"),
    ("Moti", "Dog", "Indie mix", 1, "Female", "Gentle with children"),
    ("Kalu", "Dog", "Indie", 3, "Male", "Guard-dog instincts, friendly once he knows you"),
    ("Chutki", "Cat", "Indian domestic", 1, "Female", "Curious and cuddly"),
    ("Simba", "Cat", "Indian domestic", 2, "Male", "Independent, likes window seats"),
    ("Luna", "Cat", "Indian domestic", 0.5, "Female", "Tiny explorer, litter trained"),
    ("Golu", "Dog", "Indie", 0.5, "Male", "Bouncy puppy, needs training"),
    ("Mishti", "Cat", "Indian domestic", 3, "Female", "Quiet lap cat"),
    ("Tiger", "Dog", "Indie", 5, "Male", "Three-legged and fearless"),
    ("Bholu", "Dog", "Indie", 6, "Male", "Senior gentleman, loves naps"),
    ("Coco", "Dog", "Indie mix", 2, "Female", "Energetic, great running buddy"),
]
INVENTORY = [
    ("Kennel beds", "Shelter", 30, "beds", 5), ("Rabies vaccine", "Medicine", 42, "doses", 20),
    ("Antibiotic injections", "Medicine", 12, "vials", 15), ("Surgical gauze", "Medical supply", 80, "packs", 30),
    ("Dog food (dry)", "Food", 140, "kg", 50), ("Cat food (wet)", "Food", 18, "kg", 20),
    ("Anti-tick spray", "Medicine", 9, "bottles", 10), ("Saline drip 500 ml", "Medical supply", 55, "bags", 25),
    ("Leashes and collars", "Equipment", 34, "pieces", 10), ("Rescue stretchers", "Equipment", 4, "pieces", 2),
]


def _clear(conn) -> None:
    """Empty every table, the simulated outbox and the uploaded photos."""
    dh.clear_all(conn)
    if OUTBOX_LOG.exists():
        OUTBOX_LOG.unlink()
    if UPLOAD_DIR.exists():
        shutil.rmtree(UPLOAD_DIR)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _ts(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def seed(reset: bool = False, rng_seed: int = 42, quiet: bool = False) -> bool:
    """Fill the database with demo data. Returns False if data already exists."""
    dh.ensure_files()
    with dh.transaction() as conn:
        if reset:
            _clear(conn)
        if not dh.load_table("users", conn=conn).empty:
            return False
        _build(conn, rng_seed)
    if not quiet:
        print(f"Demo data created in {DATABASE_URL.split('@')[-1]}")
    return True


def _build(conn, rng_seed: int) -> None:
    rnd = random.Random(rng_seed)
    now = datetime.now().replace(microsecond=0)
    start = now - timedelta(days=180)
    events: list[tuple[str, str, str, str, str]] = []       # (timestamp, actor, role, action, details)

    # ---------------------------------------------------------- users
    users = []
    for uid, name, email, mobile, role, pincode, password in DEMO_ACCOUNTS:
        created = start - timedelta(days=rnd.randint(5, 40))
        users.append({"user_id": uid, "name": name, "email": email, "mobile": mobile,
                                "role": role, "pincode": pincode,
                                "password_hash": hash_password(password), "created_at": _ts(created),
                                "verified": "yes"})
        events.append((_ts(created), uid, role, "USER_REGISTERED", f"{name} registered as {role}"))
    dh.insert_rows("users", users, conn=conn)
    citizens = [a[0] for a in DEMO_ACCOUNTS if a[4] in ("Citizen", "Adopter")]
    donors = [a for a in DEMO_ACCOUNTS if a[4] == "Donor"]

    # ---------------------------------------------------------- rescue cases
    cases = []
    for number in range(1, 47):
        reported = start + timedelta(minutes=rnd.randint(0, 180 * 24 * 60 - 600))
        age_days = (now - reported).days
        animal = rnd.choices(list(DESCRIPTIONS), weights=[55, 25, 8, 8, 4])[0]
        injury = rnd.choices(["Low", "Moderate", "Critical"], weights=[30, 45, 25])[0]
        pincode = rnd.choice(AREA_PINCODES)
        if age_days > 45:
            status = rnd.choices(CASE_STATUSES[2:], weights=[3, 17, 80])[0]
        elif age_days > 10:
            status = rnd.choices(CASE_STATUSES[1:], weights=[10, 15, 40, 35])[0]
        else:
            status = rnd.choices(CASE_STATUSES, weights=[35, 25, 15, 20, 5])[0]
        area = pincode[:3]
        rescuer = {"201": "U0002", "110": "U0003"}.get(area, "U0004")
        if pincode.startswith("2013"):
            rescuer = "U0004"
        location = offline_location(pincode)
        case = RescueCase(
            case_id=f"RC-{number:04d}", reporter_id=rnd.choice(citizens), animal_type=animal,
            injury_level=injury, description=rnd.choice(DESCRIPTIONS[animal]), pincode=pincode,
            address=rnd.choice(["Near metro station", "Behind the market", "Outside the school gate",
                                "Park entrance", "Near the temple", "Highway service lane", ""]),
            latitude=str(location["latitude"]), longitude=str(location["longitude"]),
            location_source="offline zone table", status=status, reported_at=_ts(reported),
            estimated_cost=str(int(DEFAULT_TREATMENT_COST[injury] * rnd.uniform(0.7, 1.5) // 100 * 100)),
        )
        events.append((case.reported_at, case.reporter_id, "Citizen", "SOS_REPORTED",
                       f"{case.case_id}: {injury} {animal.lower()} at {pincode}"))
        if status != "Reported":
            hours = rnd.uniform(0.3, 2.5) if injury == "Critical" else rnd.uniform(0.5, 7)
            assigned = reported + timedelta(hours=hours)
            case.rescuer_id, case.assigned_at = rescuer, _ts(assigned)
            events.append((case.assigned_at, rescuer, "Rescuer", "CASE_ACCEPTED", f"{case.case_id} accepted"))
            steps = CASE_STATUSES.index(status)
            notes = rnd.sample(NOTES, k=min(steps, len(NOTES)))
            last = assigned
            for note in notes:
                last = min(now, last + timedelta(hours=rnd.uniform(3, 60)))
                case.medical_notes = (case.medical_notes + " | " if case.medical_notes else "") + \
                    f"[{_ts(last)}] {dict((a[0], a[1]) for a in DEMO_ACCOUNTS)[rescuer]}: {note}"
            case.updated_at = _ts(last)
        else:
            case.updated_at = case.reported_at
        cases.append(case)
    cases.sort(key=lambda c: c.reported_at)
    for index, case in enumerate(cases, start=1):           # ids in date order
        case.case_id = f"RC-{index:04d}"
    dh.insert_rows("rescue_cases", [c.to_dict() for c in cases], conn=conn)
    funded_candidates = [c for c in cases if c.injury_level != "Low"]

    # ---------------------------------------------------------- donations
    donations = []
    for _ in range(150):
        moment = start + timedelta(minutes=rnd.randint(0, 180 * 24 * 60 - 60))
        # donations grow a little over time (awareness campaign)
        if rnd.random() < 0.35:
            moment = now - timedelta(minutes=rnd.randint(60, 70 * 24 * 60))
        uid, name, email, mobile, *_ = rnd.choices(donors, weights=[38, 30, 7, 25])[0]
        fund = rnd.choices(["General Shelter Fund", "Specific Medical Case", "Emergency Feed Fund"],
                           weights=[50, 30, 20])[0]
        amount = round(min(rnd.lognormvariate(7.3, 0.85), 60000) / 10) * 10
        if uid == "U0007":
            amount = rnd.choice([10000, 15000, 25000, 50000])
        case_id = ""
        if fund == "Specific Medical Case":
            options = [c for c in funded_candidates if c.reported_at <= _ts(moment)] or funded_candidates
            case_id = rnd.choice(options).case_id
        method = rnd.choices(["UPI", "Card"], weights=[72, 28])[0]
        if method == "UPI":
            masked = v.mask_upi(f"{name.split()[0].lower()}@ok{rnd.choice(['axis', 'hdfcbank', 'sbi', 'icici'])}")
        else:
            masked = f"{rnd.choice(['Visa', 'Mastercard', 'RuPay'])} •••• {rnd.randint(1000, 9999)}"
        status = "Failed" if rnd.random() < 0.04 else "Success"
        donations.append({
            "transaction_id": f"PC-DON-{moment:%Y%m%d}-{rnd.getrandbits(24):06X}",
            "donor_id": uid, "donor_name": name,
            "donor_email": "" if rnd.random() < 0.03 else email,
            "amount": f"{amount:.2f}", "contribution_type": fund, "case_id": case_id,
            "method": method, "payment_ref": f"pay_{rnd.getrandbits(56):014x}",
            "masked_account": masked, "status": status, "timestamp": _ts(moment),
        })
    donations.sort(key=lambda d: d["timestamp"])
    dh.insert_rows("donations", donations, conn=conn)
    for row in donations:
        events.append((row["timestamp"], row["donor_id"], "Donor", f"DONATION_{row['status'].upper()}",
                       f"{row['transaction_id']}: ₹{float(row['amount']):,.2f} to {row['contribution_type']}"))

    # ---------------------------------------------------------- allocations (never more than raised so far)
    pools = {"General Shelter Fund": 0.0, "Emergency Feed Fund": 0.0}
    purposes = {"General Shelter Fund": ["Surgery", "Medicines", "Vaccination", "Shelter maintenance", "Transport"],
                "Emergency Feed Fund": ["Food"]}
    timeline = sorted([(d["timestamp"], "don", d) for d in donations if d["status"] == "Success"] +
                      [(_ts(start + timedelta(days=d, hours=rnd.randint(9, 18))), "alloc", None)
                       for d in range(10, 180, 4)])
    number, allocations = 0, []
    for stamp, kind, row in timeline:
        if kind == "don":
            if row["contribution_type"] in pools:
                pools[row["contribution_type"]] += float(row["amount"])
            continue
        fund = rnd.choices(list(pools), weights=[70, 30])[0]
        if pools[fund] < 1500:
            continue
        open_cases = [c for c in cases if c.reported_at <= stamp and c.status != "Reported"]
        if not open_cases:
            continue
        case = rnd.choice(open_cases)
        amount = round(min(pools[fund] * rnd.uniform(0.3, 0.75), float(case.estimated_cost) * 1.1) / 100) * 100
        if amount < 500:
            continue
        pools[fund] -= amount
        number += 1
        purpose = rnd.choice(purposes[fund])
        allocations.append({"allocation_id": f"AL-{number:04d}", "case_id": case.case_id,
                                      "source_fund": fund, "amount": f"{amount:.2f}", "purpose": purpose,
                                      "allocated_by": "U0001", "allocated_at": stamp,
                                      "notes": f"{purpose} for {case.animal_type.lower()} ({case.case_id})"})
        events.append((stamp, "U0001", "Admin", "FUNDS_ALLOCATED",
                       f"AL-{number:04d}: ₹{amount:,.2f} from {fund} to {case.case_id} ({purpose})"))
    dh.insert_rows("allocations", allocations, conn=conn)

    # ---------------------------------------------------------- animals
    recovered = [c for c in cases if c.status == "Recovered"]
    animals = []
    for index, (name, species, breed, age, gender, temperament) in enumerate(ANIMALS, start=1):
        source = rnd.choice([c for c in recovered if c.animal_type == species] or recovered or [None])
        added = (datetime.strptime(source.updated_at, "%Y-%m-%d %H:%M:%S") if source
                 else now - timedelta(days=rnd.randint(5, 90)))
        animal = Animal(
            animal_id=f"A{index:03d}", name=name, species=species, breed=breed, age_years=str(age),
            gender=gender, vaccinated=rnd.choice(["yes", "yes", "no"]),
            sterilized=rnd.choice(["yes", "no"]), temperament=temperament,
            description=f"Rescued{' from ' + source.address.lower() if source and source.address else ''} "
                        f"and fully recovered. {temperament}.",
            status="Adopted" if index in (3, 9) else "Available",
            case_id=source.case_id if source else "", added_at=_ts(added),
        )
        animals.append(animal.to_dict())
    dh.insert_rows("animals", animals, conn=conn)

    # ---------------------------------------------------------- adoption applications
    applicants = [("U0012", "Riya Bansal"), ("U0013", "Aditya Rao"), ("U0009", "Karan Malhotra"),
                  ("U0010", "Pooja Yadav")]
    plans = [("A003", 0, "Approved"), ("A009", 1, "Approved"), ("A001", 0, ""), ("A005", 1, ""),
             ("A002", 2, ""), ("A010", 3, ""), ("A007", 3, "Rejected")]
    applications = []
    for number, (animal_id, who, decision) in enumerate(plans, start=1):
        uid, name = applicants[who]
        good = who in (0, 1)
        answers = {key: (list(q["options"])[0 if good and rnd.random() < 0.7 else rnd.randint(0, len(q["options"]) - 1)])
                   for key, q in QUESTIONNAIRE.items()}
        submitted = now - timedelta(days=rnd.randint(1, 60), hours=rnd.randint(0, 12))
        app = AdoptionApplication(application_id=f"AP-{number:04d}", applicant_id=uid,
                                  applicant_name=name, animal_id=animal_id,
                                  reason="We have space at home and want to give a rescued animal a family.",
                                  submitted_at=_ts(submitted), **answers)
        if decision:
            app.status, app.reviewed_by = decision, "U0001"
            app.reviewed_at = _ts(submitted + timedelta(days=2))
        applications.append(app.to_dict())
        events.append((app.submitted_at, uid, "Adopter", "ADOPTION_APPLIED",
                       f"{app.application_id} for {animal_id}: score {app.score}"))

    dh.insert_rows("adoption_applications", applications, conn=conn)

    # ---------------------------------------------------------- inventory
    dh.insert_rows("inventory", [
        {"item_id": f"INV-{index:03d}", "item": item, "category": category, "quantity": qty,
         "unit": unit, "reorder_level": reorder, "updated_at": _ts(now - timedelta(days=rnd.randint(0, 10)))}
        for index, (item, category, qty, unit, reorder) in enumerate(INVENTORY, start=1)], conn=conn)

    # ---------------------------------------------------------- audit trail in time order
    events.sort()
    events.append((_ts(now), "system", "System", "DEMO_DATA_LOADED", "Sample data created"))
    dh.log_events(events, conn=conn)


if __name__ == "__main__":
    seed(reset=True)
