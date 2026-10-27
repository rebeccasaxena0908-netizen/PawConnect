"""
Checks Python, the libraries, the database, e-mail and (optionally) internet access.

    python check_setup.py                              # check everything
    python check_setup.py --send-test you@example.com  # also send one real test e-mail
"""
import argparse
import importlib
import sys

parser = argparse.ArgumentParser(description="PawConnect setup check")
parser.add_argument("--send-test", metavar="EMAIL", help="send one real test e-mail to this address")
args = parser.parse_args()

OK, BAD, WARN = "✅", "❌", "⚠️ "
problems = 0

print("PawConnect setup check\n")
version = sys.version_info
if version >= (3, 10):
    print(f"{OK} Python {version.major}.{version.minor}.{version.micro}")
else:
    print(f"{BAD} Python {version.major}.{version.minor} – PawConnect needs 3.10 or newer")
    problems += 1

for module, label in [("streamlit", "Streamlit"), ("PyQt6.QtWidgets", "PyQt6"), ("pandas", "pandas"),
                      ("numpy", "NumPy"), ("matplotlib", "Matplotlib"), ("seaborn", "seaborn"),
                      ("requests", "requests"), ("PIL", "Pillow"), ("sqlalchemy", "SQLAlchemy"),
                      ("alembic", "Alembic"), ("flask", "Flask"), ("flask_smorest", "flask-smorest"),
                      ("jwt", "PyJWT"), ("dotenv", "python-dotenv"), ("flask_cors", "flask-cors")]:
    try:
        mod = importlib.import_module(module)
        top = importlib.import_module(module.split(".")[0])
        print(f"{OK} {label} {getattr(top, '__version__', getattr(mod, 'PYQT_VERSION_STR', ''))}")
    except ImportError as error:
        print(f"{BAD} {label} missing ({error}). Run: pip install -r requirements.txt")
        problems += 1

try:
    from analytics import data_handler as dh
    from analytics.sample_data import seed
    dh.ensure_files()
    created = seed(quiet=True)
    counts = {name: len(dh.load_table(name)) for name in ("users", "rescue_cases", "donations")}
    from config import DATABASE_URL
    print(f"{OK} Database {DATABASE_URL.split('@')[-1]} ready{' (demo data created)' if created else ''}: "
          + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in counts.items()))
except Exception as error:  # noqa: BLE001 – show any problem to the student
    print(f"{BAD} Database problem: {error}")
    print("    Check DATABASE_URL in .env – or remove it to use the built-in SQLite file.")
    problems += 1

try:
    import requests
    requests.get("https://api.postalpincode.in/pincode/201001", timeout=4)
    print(f"{OK} Internet: pincode lookup reachable")
except Exception:  # noqa: BLE001
    print(f"{WARN} No internet – the app still works, locations use the offline pincode table")

import config  # noqa: E402

if config.EMAIL_ENABLED:
    print(f"{OK} E-mail: SMTP configured ({config.SMTP_HOST}:{config.SMTP_PORT} as {config.SMTP_USER})")
    if not args.send_test:
        print("    Send a real test e-mail with:  python check_setup.py --send-test you@example.com")
else:
    print(f"{WARN} E-mail: SMTP not configured – e-mails are simulated in data/outbox.log and the OTP is shown"
          " on screen. Set SMTP_USER and SMTP_PASSWORD in .env to send real e-mails (see README).")

if args.send_test:
    if not config.EMAIL_ENABLED:
        print(f"{BAD} Can't send a test e-mail: SMTP_USER and SMTP_PASSWORD are not set in .env")
        problems += 1
    else:
        from services import email_service
        subject, text, html = email_service.welcome_email("PawConnect tester", "Test")
        result = email_service.send_email(args.send_test, "PawConnect test e-mail", text, html)
        if result["ok"]:
            print(f"{OK} Test e-mail sent to {args.send_test} – check the inbox (and the spam folder).")
        else:
            print(f"{BAD} Test e-mail failed: {result['error']}")
            if "app password" in result["error"]:
                print("    Gmail needs 2-Step Verification ON and an App password (not your normal password).")
            elif "network" in result["error"]:
                print("    Port 587 may be blocked (college/office Wi-Fi). Try a phone hotspot.")
            problems += 1

print("\nAll good! Run:  python main.py --all" if not problems else f"\n{problems} problem(s) to fix above.")
sys.exit(1 if problems else 0)
