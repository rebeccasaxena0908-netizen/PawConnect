"""
Shared test setup: temporary data folder + temporary SQLite database + project root on sys.path.

This module MUST be imported before anything from the project, because config.py
reads these environment variables once at import time. Setting DATABASE_URL here
(overriding any .env file) guarantees the tests never touch data/pawconnect.db
or a PostgreSQL server.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMP_DATA = tempfile.mkdtemp(prefix="pawconnect-test-")
os.environ["PAWCONNECT_DATA_DIR"] = TEMP_DATA
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEMP_DATA) / 'test.db'}"
os.environ["PAWCONNECT_MODE"] = "local"            # UI tests talk to the API in-process
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Never call real services from tests. These are set to "" rather than removed:
# config.py loads .env without overriding existing variables, so an empty value
# here stops your real SMTP / Razorpay keys in .env from being picked up.
for key in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET",
            "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "PAWCONNECT_JWT_SECRET"):
    os.environ[key] = ""
os.environ["PAWCONNECT_SHOW_OTP"] = "1"


def fresh_demo_data() -> None:
    from analytics.sample_data import seed
    seed(reset=True, quiet=True)
