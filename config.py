"""
PawConnect – every setting in one place.

Change values here instead of hunting through the code.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Settings can come from a .env file (see .env.example). Real environment
# variables always win, so the tests can point everything at a temp folder.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=False)
except ImportError:          # python-dotenv not installed – plain env vars still work
    pass

# ---------------------------------------------------------------- paths
# PAWCONNECT_DATA_DIR lets the tests use a temporary folder instead of data/.
DATA_DIR = Path(os.environ.get("PAWCONNECT_DATA_DIR", BASE_DIR / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"
OUTBOX_LOG = DATA_DIR / "outbox.log"          # one status line per e-mail (never the body)

# ---------------------------------------------------------------- database
# SQLite file by default. For PostgreSQL set, for example:
#   DATABASE_URL=postgresql+psycopg://pawconnect:pawconnect@localhost:5432/pawconnect
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'pawconnect.db'}"
DB_ECHO = os.environ.get("PAWCONNECT_DB_ECHO", "0") == "1"   # print every SQL statement

APP_NAME = "PawConnect"
APP_TAGLINE = "Stray Animal Rescue, Medical Aid & Adoption Network"
ORG_NAME = "PawConnect Animal Welfare Trust"
ORG_80G_NO = "AAATP1234F/80G/2026-27"         # sample 80G number printed on receipts

# ---------------------------------------------------------------- roles
ROLES = ["Citizen", "Rescuer", "Donor", "Adopter", "Admin"]
SELF_REGISTER_ROLES = ["Citizen", "Rescuer", "Donor", "Adopter"]   # admins are created by the trust

# ---------------------------------------------------------------- rescue
ANIMAL_TYPES = ["Dog", "Cat", "Cow", "Bird", "Monkey", "Other"]
INJURY_LEVELS = ["Low", "Moderate", "Critical"]
CASE_STATUSES = ["Reported", "Assigned", "In Transit", "Sheltered/In Treatment", "Recovered"]
DEFAULT_TREATMENT_COST = {"Low": 1500, "Moderate": 6000, "Critical": 15000}   # ₹ estimate
ALLOWED_PHOTO_TYPES = ["jpg", "jpeg", "png", "webp"]
MAX_PHOTO_MB = 8

# ---------------------------------------------------------------- donations
CONTRIBUTION_TYPES = ["General Shelter Fund", "Specific Medical Case", "Emergency Feed Fund"]
ALLOCATABLE_FUNDS = ["General Shelter Fund", "Emergency Feed Fund"]
ALLOCATION_PURPOSES = ["Surgery", "Medicines", "Vaccination", "Food", "Shelter maintenance", "Transport"]
PAYMENT_METHODS = ["UPI", "Card", "Razorpay"]   # Razorpay = real test-mode checkout
DONATION_STATUSES = ["Pending", "Success", "Failed"]
MIN_DONATION = 10
MAX_DONATION = 1_000_000
PAYMENT_SECRET = os.environ.get("PAWCONNECT_PAYMENT_SECRET", "pawconnect-sandbox-secret")
DECLINED_TEST_CARD = "4000000000000002"       # sandbox card that is always declined
DECLINED_TEST_UPI = "fail@upi"                # sandbox UPI handle that is always declined

# ---------------------------------------------------------------- adoption
PREAPPROVAL_THRESHOLD = 65                     # score out of 100
APPLICATION_STATUSES = ["Pre-Approved", "Under Review", "Approved", "Rejected", "Closed"]
ANIMAL_STATUSES = ["Available", "Adopted"]

# ---------------------------------------------------------------- auth / OTP
OTP_LENGTH = 6
OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 3
OTP_RESEND_COOLDOWN = 30                       # seconds between two codes to the same address
OTP_MAX_PER_HOUR = 5                           # codes per e-mail address per hour
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 60
PASSWORD_ITERATIONS = 200_000

# ---------------------------------------------------------------- e-mail (all notifications)
# Set these in .env (never in the code). For Gmail, SMTP_PASSWORD must be an *app password*.
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_PORT = int(os.environ.get("SMTP_PORT") or 587)
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM") or f"PawConnect <{SMTP_USER}>"
# Real e-mails only when both are set; otherwise every e-mail is simulated (data/outbox.log).
EMAIL_ENABLED = bool(SMTP_USER and SMTP_PASSWORD)
# Without real e-mail the OTP is shown on screen (demo mode). With real e-mail – never.
SHOW_OTP_ON_SCREEN = (not EMAIL_ENABLED) and os.environ.get("PAWCONNECT_SHOW_OTP", "1") == "1"

# ---------------------------------------------------------------- PawConnect REST API (Flask)
API_HOST = os.environ.get("PAWCONNECT_API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("PAWCONNECT_API_PORT", "5000"))
API_URL = os.environ.get("PAWCONNECT_API_URL", f"http://{API_HOST}:{API_PORT}")
# How the web app and desktop console reach the data:
#   api   – over HTTP to the Flask API (python main.py --all)
#   local – run the API code in-process, no server needed (quick offline demos)
#   auto  – use the API if it answers, otherwise fall back to local   (default)
UI_MODE = os.environ.get("PAWCONNECT_MODE", "auto").lower()
API_TIMEOUT = float(os.environ.get("PAWCONNECT_API_TIMEOUT", "15"))
# Sign-in tokens. Set PAWCONNECT_JWT_SECRET in .env so tokens survive an API restart;
# without it a random secret is made each time the API starts.
JWT_SECRET = os.environ.get("PAWCONNECT_JWT_SECRET", "")
JWT_EXPIRY_SECONDS = 3600
LOGIN_FAILURES_PER_MINUTE = 5
OTP_SENDS_PER_MINUTE = 10           # per IP – each address also has its own limits (see OTP_*)
OTP_VERIFIES_PER_MINUTE = 10
WEB_ORIGIN = os.environ.get("PAWCONNECT_WEB_ORIGIN", "http://localhost:8501")   # only origin allowed by CORS

# ---------------------------------------------------------------- external APIs
GEOCODE_TIMEOUT = 5
USER_AGENT = "PawConnect/1.0 (BCA student project)"
INDIA_POST_API = "https://api.postalpincode.in/pincode/{pincode}"
NOMINATIM_API = "https://nominatim.openstreetmap.org/search"

# ---------------------------------------------------------------- CSV schemas (column order on disk)
SCHEMAS = {
    "users": ["user_id", "name", "email", "mobile", "role", "pincode", "password_hash",
              "created_at", "verified"],
    "rescue_cases": ["case_id", "reporter_id", "animal_type", "injury_level", "description",
                     "pincode", "address", "latitude", "longitude", "location_source",
                     "photo_path", "status", "rescuer_id", "reported_at", "assigned_at",
                     "updated_at", "medical_notes", "estimated_cost"],
    "donations": ["transaction_id", "donor_id", "donor_name", "donor_email", "amount",
                  "contribution_type", "case_id", "method", "payment_ref", "masked_account",
                  "status", "timestamp"],
    "allocations": ["allocation_id", "case_id", "source_fund", "amount", "purpose",
                    "allocated_by", "allocated_at", "notes"],
    "animals": ["animal_id", "name", "species", "breed", "age_years", "gender", "vaccinated",
                "sterilized", "temperament", "description", "photo_path", "status", "case_id",
                "added_at"],
    "adoption_applications": ["application_id", "applicant_id", "applicant_name", "animal_id",
                              "housing", "experience", "hours_alone", "family", "budget",
                              "reason", "score", "status", "submitted_at", "reviewed_by",
                              "reviewed_at"],
    "inventory": ["item_id", "item", "category", "quantity", "unit", "reorder_level",
                  "updated_at"],
}

# ---------------------------------------------------------------- look ("Dusk Rose")
# Dark, warm and caring – like a shelter at dusk. EVERY colour used by the web
# app, the desktop console, the charts and the payment page comes from here, so
# changing a value once re-themes everything. All text colours keep at least
# 4.5:1 contrast on bg, surface and raised (WCAG AA).
COLORS_DARK = {
    "bg": "#151216",          # page background (warm charcoal)
    "surface": "#1E1A20",     # cards
    "raised": "#272229",      # inner panels, inputs, table header, hover
    "border": "#362F39",      # 1px borders and gridlines
    "text": "#F0E9EC",        # main text
    "muted": "#A89BA2",       # secondary text, labels, axis text
    "accent": "#F28FAD",      # dusty rose: primary buttons, key numbers, active tab, focus ring
    "accent2": "#8FB8F2",     # soft blue: second chart series, links, info
    "accent3": "#F2C98F",     # warm sand: third chart series, "moderate" and warnings
    "danger": "#F5877F",      # critical injuries, failed payments, errors
    "success": "#8FD9B6",     # recovered, approved, successful payments
    "violet": "#C4A7F2",      # fifth chart colour
    # derived helpers
    "accent_fill": "#F28FAD",         # primary button gradient start …
    "accent_fill_deep": "#E5779A",    # … and end
    "on_accent": "#151216",           # text on rose fills = the page colour, never white
    "border_strong": "#4A4150",
    "glow_rose": "rgba(242,143,173,.15)",    # radial glow, top-right
    "glow_blue": "rgba(143,184,242,.11)",    # radial glow, bottom-left
    "highlight": "rgba(255,255,255,.045)",   # faint inner top highlight on cards
    "shadow": "rgba(0,0,0,.45)",
}
# Light theme = the original cream and coral look. The accents used as TEXT are
# deeper shades of the same hues so they pass 4.5:1 on cream.
COLORS_LIGHT = {
    "bg": "#FFF8F1", "surface": "#FFFFFF", "raised": "#F6E7D8", "border": "#EBDACB",
    "text": "#2B2522", "muted": "#5E534D",
    "accent": "#A6432D", "accent2": "#1F6F66", "accent3": "#80560F", "danger": "#A8392E",
    "success": "#256B4A", "violet": "#6B4FA8",
    "accent_fill": "#EE8A6F", "accent_fill_deep": "#E8735A", "on_accent": "#2B2522",
    "border_strong": "#D9C3AE",
    "glow_rose": "rgba(247,180,140,.30)", "glow_blue": "rgba(47,143,131,.16)",
    "highlight": "rgba(255,255,255,.8)", "shadow": "rgba(196,85,61,.10)",
}
THEMES = {"dark": COLORS_DARK, "light": COLORS_LIGHT}
DEFAULT_THEME = "dark"
COLORS = COLORS_DARK

CHART_PALETTE = ["#8FB8F2", "#F28FAD", "#F2C98F", "#8FD9B6", "#C4A7F2"]

FONTS = {
    "heading": "Fraunces",          # headings and big numbers
    "body": "Nunito Sans",
    "google_css": "https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700"
                  "&family=Nunito+Sans:wght@400;600;700&display=swap",
}


def chart_palette(colors: dict = COLORS) -> list[str]:
    """Series colours: CHART_PALETTE on dark, the same hues (deeper) on the light theme."""
    if colors is COLORS_DARK:
        return CHART_PALETTE
    return [colors[k] for k in ("accent2", "accent", "accent3", "success", "violet")]


def status_colors(colors: dict = COLORS) -> dict[str, str]:
    """Rescue stage → colour."""
    return {"Reported": colors["danger"], "Assigned": colors["accent3"], "In Transit": colors["accent"],
            "Sheltered/In Treatment": colors["accent2"], "Recovered": colors["success"]}


def injury_colors(colors: dict = COLORS) -> dict[str, str]:
    return {"Critical": colors["danger"], "Moderate": colors["accent3"], "Low": colors["success"]}


STATUS_COLORS = status_colors()
