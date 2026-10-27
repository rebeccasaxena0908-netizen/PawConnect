# 🐾 PawConnect

**Stray Animal Rescue, Medical Aid & Adoption Network** – Advanced Python (BCA306-5) project.

Citizens report injured strays, field rescuers pick them up, donors fund treatment with full
transparency, adopters give recovered animals a home, and shelter admins run everything from a
Streamlit web app and a PyQt6 desktop console – all talking to one Flask REST API backed by a real
SQL database.

---

## Architecture

```
 ┌──────────────────────────┐   ┌──────────────────────────┐   ┌──────────────────┐
 │ Streamlit web app        │   │ PyQt6 desktop console    │   │ curl / Postman / │
 │ ui/web_app.py            │   │ ui/desktop_gui.py        │   │ Swagger at /docs │
 │ ui/components/*.py       │   │                          │   │                  │
 └────────────┬─────────────┘   └────────────┬─────────────┘   └────────┬─────────┘
              └──────── PawConnectClient (api/client.py) ───────┐       │
                        requests.Session + JWT                  │       │
                        (or in-process when PAWCONNECT_MODE=local)      │
                                                                ▼       ▼
                 ┌───────────────────────────────────────────────────────────────┐
                 │ Flask REST API  (api/)  – blueprints, JWT, roles, rate limits │
                 │ auth · cases · donations · payments · funds · animals ·       │
                 │ adoption · inventory · users · analytics · admin · health     │
                 └───────────────────────────────┬───────────────────────────────┘
                                                 ▼
                 ┌───────────────────────────────────────────────────────────────┐
                 │ core/workflows.py – every business rule, in transactions      │
                 │ core/models.py (OOP) · core/validators.py (regex)             │
                 │ services/: email_service · payment_razorpay · api_service     │
                 └───────────────────────────────┬───────────────────────────────┘
                                                 ▼
                 ┌───────────────────────────────────────────────────────────────┐
                 │ analytics/data_handler.py – pandas.read_sql, CSV/XML export   │
                 │ db/ – SQLAlchemy 2 engine, tables, Alembic migrations         │
                 └───────────────────────────────┬───────────────────────────────┘
                                                 ▼
                        SQLite  data/pawconnect.db     or    PostgreSQL
```

The UIs never touch the database: they only call `PawConnectClient`. That makes the API the single
place where permissions, validation and transactions are enforced.

---

## Setup on a Mac (Apple Silicon) with VS Code

1. Install **Python 3.11** from python.org (not the built-in `/usr/bin/python3`).
2. Open the folder in VS Code and run in the terminal:

   ```bash
   python3.11 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   python check_setup.py
   ```

3. Run everything:

   ```bash
   python main.py --all        # REST API + web app → http://localhost:8501
   ```

That's it – no database server, payment account or mail account is needed. The database
(`data/pawconnect.db`) is created by the Alembic migrations and filled with demo data the first time.

| Command | What it does |
|---|---|
| `python main.py --all` | starts the API (port 5000), waits for it, then the web app |
| `python main.py --api` | only the API · Swagger docs at `http://127.0.0.1:5000/docs` |
| `python main.py` | only the web app (uses the API if it's running, otherwise runs it in-process) |
| `python main.py --desktop` | PyQt6 admin console |
| `python main.py --reset-data` | empty the database and load the demo data again |
| `python main.py --test` | run all tests (they use a temporary database, never yours) |
| `python scripts/import_csv_to_db.py` | one-time import of the old `data/*.csv` files into the database |

> **macOS and port 5000:** AirPlay Receiver uses port 5000 on recent Macs. `--all` notices this and
> moves the API to 5001 automatically. To keep 5000, switch off *System Settings → General → AirDrop &
> Handoff → AirPlay Receiver*.

**Local mode:** `PAWCONNECT_MODE=local python main.py` runs the API code inside the web-app process –
no server, handy for an offline demo. `PAWCONNECT_MODE=api` forces HTTP; the default `auto` uses the API
when it answers and falls back to local otherwise.

---

## Configuration (`.env`)

```bash
cp .env.example .env      # then edit .env – it is in .gitignore, never commit it
```

Every setting is listed with a comment in `.env.example`. The important ones:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite file | `postgresql+psycopg://pawconnect:pawconnect@localhost:5432/pawconnect` for Postgres |
| `PAWCONNECT_JWT_SECRET` | random per start | sign-in token secret – set it so tokens survive an API restart |
| `SMTP_USER` / `SMTP_PASSWORD` | empty | real e-mails (OTP, receipts, updates); empty = simulated |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | empty | real Razorpay **test-mode** checkout; empty = sandbox |
| `PAWCONNECT_MODE` | `auto` | `api`, `local` or `auto` (see above) |

### PostgreSQL (optional)

```bash
docker compose up -d                       # starts Postgres 16 from docker-compose.yml
echo 'DATABASE_URL=postgresql+psycopg://pawconnect:pawconnect@localhost:5432/pawconnect' >> .env
python main.py --all                       # migrations create the tables, demo data is loaded
python scripts/import_csv_to_db.py --replace   # (optional) load the old CSV data instead
```

No code changes: the same SQLAlchemy code runs on SQLite and PostgreSQL. Run migrations by hand with
`alembic upgrade head`; see the SQL without running it with `alembic upgrade head --sql`.

### E-mail with Gmail

PawConnect sends **every notification by e-mail**: sign-up codes, password-reset codes, a welcome
message, donation receipts (with the 80G note), rescue updates to the person who reported the animal,
and adoption decisions. There is no SMS for now (`services/sms_service.py` is a placeholder).

1. Use a Gmail account for the shelter (a new one is best).
2. Google Account → **Security** → turn on **2-Step Verification**.
3. Search for **App passwords** in your Google Account, create one called "PawConnect" and copy the
   16-letter password.
4. In `.env`:

   ```ini
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=pawconnect.shelter@gmail.com
   SMTP_PASSWORD=abcdefghijklmnop        # the app password, not your Gmail password
   SMTP_FROM=PawConnect <pawconnect.shelter@gmail.com>
   ```

5. Test it: `python check_setup.py --send-test you@example.com`

Recipients see the sender as **PawConnect &lt;pawconnect.shelter@gmail.com&gt;** (whatever `SMTP_FROM`
says; by default `PawConnect <SMTP_USER>`). E-mails are dark "Dusk Rose" cards built with inline CSS
and tables so Gmail shows them correctly, plus a plain-text version.

Without `SMTP_USER`/`SMTP_PASSWORD` nothing is sent: each e-mail adds one status line to
`data/outbox.log` and the sign-up code is shown on screen (demo mode). With real e-mail the code is
**never** shown on screen. The log never contains message bodies, codes or passwords.

**E-mail troubleshooting**

- *Nothing arrives* – look in the **spam** folder; mark it "Not spam" once.
- *"Application-specific password required" / sign-in failed* – you used the normal Gmail password, or
  2-Step Verification is off. Create an app password (step 3).
- *"Couldn't reach the mail server"* – port 587 is blocked (some college/office Wi-Fi); try a hotspot.
- *Gmail limit* – a normal Gmail account can send roughly **500 e-mails a day**; enough for a demo.
- *"Please wait 30 seconds"* – a new code can be requested every 30 s, at most 5 per address per hour.

### Razorpay test keys (optional)

1. Sign up at [dashboard.razorpay.com](https://dashboard.razorpay.com) and switch to **Test mode**.
2. **Settings → API Keys → Generate Test Key** → put the Key ID and Secret in `.env`
   (`RAZORPAY_KEY_ID=rzp_test_…`, `RAZORPAY_KEY_SECRET=…`).
3. Restart. The donor form now offers **Razorpay Checkout (test)**: PawConnect creates an order, you pay
   on Razorpay's own page (UPI `success@razorpay` or a test card from Razorpay's docs), and the payment
   is trusted only after its HMAC signature is verified.
4. Webhooks (optional, needs a public URL e.g. ngrok): **Settings → Webhooks →** `https://…/payments/webhook`,
   events `payment.captured` + `payment.failed`, and the same secret in `RAZORPAY_WEBHOOK_SECRET`.

Without keys the built-in sandbox gateway is used: any valid UPI ID (e.g. `ananya@okaxis`) or card
`4111 1111 1111 1111` succeeds; `fail@upi` and card `4000 0000 0000 0002` are declined.

---

## Demo accounts

| Role | E-mail | Password |
|---|---|---|
| Admin | admin@pawconnect.org | Admin@123 |
| Rescuer | arjun.rescue@pawconnect.org (area 201xxx) | Rescuer@123 |
| Rescuer | fatima.rescue@pawconnect.org (area 110xxx) | Rescuer@123 |
| Donor | ananya@example.com | Donor@123 |
| Citizen | karan@example.com | Citizen@123 |
| Adopter | riya@example.com | Adopter@123 |

Sign in with the e-mail or the mobile number (e.g. `9810000001` for the admin). New accounts confirm
their **e-mail** with a 6-digit code; the mobile number is optional. "Forgot password?" on the sign-in
tab e-mails a reset code.

---

## REST API

Interactive docs: **http://127.0.0.1:5000/docs** (Swagger UI – sign in with `POST /auth/login`, click
**Authorize**, paste the token). Every error looks like `{"error": "...", "details": ["..."]}`.

Status codes: `200/201` ok · `400` malformed body · `401` not signed in / token expired · `402` payment
declined · `403` role not allowed · `404` not found · `409` conflict (case already taken, not enough
money) · `422` validation · `429` too many attempts · `503` e-mail could not be sent.

```bash
API=http://127.0.0.1:5000
# sign in (5 failed attempts per minute per IP → 429)
TOKEN=$(curl -s -X POST $API/auth/login -H 'Content-Type: application/json' \
  -d '{"identifier":"admin@pawconnect.org","password":"Admin@123"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"

curl $API/health
curl -H "$AUTH" $API/me
curl -H "$AUTH" $API/cases
curl -H "$AUTH" $API/analytics/summary
curl -H "$AUTH" $API/funds/overview

# sign up: e-mail a code, then verify it (demo mode returns "demo_otp")
curl -X POST $API/auth/register/start -H 'Content-Type: application/json' \
  -d '{"name":"Neha Gupta","email":"neha@example.com","role":"Donor","pincode":"201001","password":"Good@1234"}'
curl -X POST $API/auth/register/verify -H 'Content-Type: application/json' -d '{"email":"neha@example.com","otp":"123456"}'

# citizen reports an SOS, then uploads a photo
curl -X POST $API/cases -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"animal_type":"Dog","injury_level":"Critical","description":"Dog hit by a bike","pincode":"201001","use_network":false}'
curl -X POST $API/cases/RC-0047/photo -H "$AUTH" -F photo=@dog.jpg

# rescuer accepts (409 if someone was faster) and moves it on
curl -X POST $API/cases/RC-0047/accept -H "$AUTH"
curl -X POST $API/cases/RC-0047/advance -H "$AUTH" -H 'Content-Type: application/json' -d '{"note":"Picked up"}'

# donor gives by UPI (sandbox), gets the receipt
curl -X POST $API/donations -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"amount":"1500","contribution_type":"General Shelter Fund","method":"UPI","upi":"ananya@okaxis"}'
curl -H "$AUTH" $API/donations/PC-DON-20261027-AB19E2/receipt

# admin allocates money (409 if the fund doesn't have enough) and reviews an adoption
curl -X POST $API/funds/allocate -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"case_id":"RC-0047","amount":"3000","purpose":"Surgery","source_fund":"General Shelter Fund"}'
curl -X POST $API/adoption/applications/AP-0003/review -H "$AUTH" -H 'Content-Type: application/json' -d '{"decision":"Approved"}'
curl -H "$AUTH" "$API/admin/export/donations?format=xml" -o donations.xml
curl -H "$AUTH" $API/admin/audit.xml -o audit_logs.xml
```

Full endpoint list: `POST /auth/login`, `POST /auth/logout`, `GET /me`, `POST /auth/register/start`,
`POST /auth/register/verify`, `POST /auth/password/forgot`, `POST /auth/password/reset` ·
`GET/POST /cases`, `GET /cases/<id>`, `POST /cases/<id>/accept|advance|notes|assign|status`,
`GET/POST /cases/<id>/photo`, `POST /cases/import` · `POST/GET /donations`, `GET /donations/<id>`,
`GET /donations/<id>/receipt` · `GET /payments/config`, `GET /payments/checkout/<id>`,
`POST /payments/razorpay/verify`, `POST /payments/webhook` · `GET /funds/overview`,
`POST /funds/allocate`, `GET /funds/allocations`, `GET /funds/case-funding` · `GET/POST /animals` ·
`GET /adoption/questionnaire`, `GET/POST /adoption/applications`, `POST /adoption/applications/<id>/review` ·
`GET/PUT /inventory` · `GET /users`, `GET /users/rescuers` · `GET /analytics/summary`, `GET /analytics/impact` ·
`GET /admin/audit`, `GET /admin/audit.xml`, `GET /admin/tables/<name>`, `GET /admin/export/<name>`,
`POST /admin/backup` · `GET /health`.

---

## What each role can do

| Role | Features |
|---|---|
| **Citizen** | SOS form (animal, injury level, description, pincode, landmark, photo) → pincode geocoded to map coordinates; follow own reports (e-mailed at every stage); browse and apply for adoption |
| **Rescuer** | SOS queue for their area (first 3 pincode digits), most critical first; accept (only one rescuer can win); move through `Assigned → In Transit → Sheltered/In Treatment → Recovered`; medical notes and cost estimate; map |
| **Donor** | Give to General Shelter Fund, a Specific Medical Case, or Emergency Feed Fund by UPI/card (sandbox) or Razorpay test checkout; e-mailed receipt with ID `PC-DON-YYYYMMDD-XXXXXX` and 80G note; history; transparency dashboard |
| **Adopter** | Catalogue, 5-question screening scored out of 100 (≥ 65 = auto **Pre-Approved**, e-mailed), application status |
| **Admin** | KPIs and charts, fund allocation (can never exceed what's available, even with two admins clicking at once), assign rescuers, approve/reject adoptions, list animals, inventory and beds, users, CSV/XML export, backup, data quality, audit log |

The **desktop console** (admins only) has a dashboard with charts, rescue cases (assign, advance,
import cases recorded offline from CSV – try `data/sample_offline_cases.csv`), donations and fund
allocation, editable inventory, and the audit log with XML export.

---

## Database

| Table | Notes |
|---|---|
| `users` | PK `user_id`; UNIQUE e-mail; mobile optional but UNIQUE when given; CHECK role |
| `rescue_cases` | FK reporter → users, rescuer → users; CHECK status, injury level, animal type; a case past *Reported* must have a rescuer; indexes on status, pincode, (status, pincode) |
| `donations` | FK donor → users, case → rescue_cases; amount > 0; CHECK fund, method, status; index on timestamp |
| `allocations` | FK case → rescue_cases, allocated_by → users; amount > 0; CHECK fund and purpose |
| `animals`, `adoption_applications`, `inventory` | FKs, CHECK status / score 0–100 / quantity ≥ 0 |
| `audit_events` | replaces `audit_logs.xml`; the XML file is still produced on export |

- **Money is stored as whole paise in BIGINT** (`₹12.50` → `1250`) through the `Money` column type in
  `db/tables.py`, so totals are exact – no floats.
- **Transactions:** donation + audit entry, allocation + case note + audit entry, and adoption decision +
  animal status + closing other applications each commit together or not at all.
- **Race conditions:** accepting a case is `UPDATE … WHERE status = 'Reported'` and checks the row count;
  allocating money locks the allocations table (SQLite: `BEGIN IMMEDIATE`, PostgreSQL: `LOCK TABLE`)
  before reading the balance. Both are tested with real threads.
- **Migrations:** `db/migrations/versions/0001_initial_schema.py`, `0002_optional_mobile.py`.

---

## Look and feel – "Dusk Rose"

Dark, warm and caring, like a shelter at dusk: warm charcoal page with a soft rose glow, cards with a
1px border, dusty-rose buttons and key numbers, soft blue for information, warm sand for warnings,
mint for good news. Fraunces for headings and numbers, Nunito Sans for text, tabular figures for money.
Every colour lives in `config.COLORS` (and `COLORS_LIGHT`), and the web CSS, the desktop QSS, the charts,
the e-mails and the payment page are all generated from it. All text meets 4.5:1 contrast.
The sidebar has a 🌙 dark/light switch (dark by default; the light theme is the original cream and
coral). The choice is remembered in a cookie.

---

## Screenshots

All taken with Playwright (web) and `widget.grab()` (desktop) on the demo data. More are in
[`docs/screenshots/`](docs/screenshots/) – each page at 1440 px and 390 px (phone), dark and light.

| Sign-in (dark) | Sign-in (light) |
|---|---|
| ![Sign-in, dark](docs/screenshots/web/desktop-dark-signin.png) | ![Sign-in, light](docs/screenshots/web/desktop-light-signin.png) |

| Rescuer dashboard | Adopter dashboard |
|---|---|
| ![Rescuer](docs/screenshots/web/desktop-dark-rescuer.png) | ![Adopter](docs/screenshots/web/desktop-dark-adopter.png) |

| Admin – fund allocation | Phone (390 px) |
|---|---|
| ![Admin funds](docs/screenshots/web/desktop-dark-admin-funds.png) | ![Phone sign-in](docs/screenshots/web/phone-dark-signin.png) |

| Desktop console – dashboard | Desktop console – rescue cases |
|---|---|
| ![Desktop dashboard](docs/screenshots/desktop/qt-dashboard.png) | ![Desktop cases](docs/screenshots/desktop/qt-cases.png) |

---

## Curriculum mapping (BCA306-5)

| Unit | Where to find it |
|---|---|
| **1 – OOP** | `core/models.py`: abstract `User` (ABC + `@abstractmethod`) → `Citizen` → `Adopter`, `Rescuer`, `Donor`, `Admin` with permission sets (reused by the API's `@require_permission`); dataclasses `RescueCase` (status machine), `DonationTransaction`, `FundAllocation`, `Animal`, `AdoptionApplication`; `api/client.py` exception hierarchy; `db/tables.Money` (`TypeDecorator` subclass) |
| **1 – Regular expressions** | `core/validators.py`: mobile `^[6-9]\d{9}$`, e-mail, UPI, pincode `^[1-9][0-9]{5}$`, card/expiry/CVV/amount/OTP, password strength, HTML/CSV-injection sanitising, Luhn check – used by the forms **and** the API schemas (`api/schemas.matches()`) |
| **1 – PyQt** | `ui/desktop_gui.py`: `QMainWindow`, `QTabWidget`, `QTableWidget`, `QDialog` login, `QFormLayout`, `QFileDialog`, `QPalette`, matplotlib `FigureCanvasQTAgg`, QSS generated from `config.COLORS` |
| **2 – APIs & JSON** | `services/api_service.py`: India Post + OpenStreetMap with `requests`/`json`/`urllib`, HMAC-signed sandbox gateway · `services/payment_razorpay.py`: Razorpay orders, checkout and webhook signatures · `services/email_service.py`: `smtplib` + `EmailMessage`, background threads · `api/client.py`: `requests.Session`, JSON, timeouts · JWT with PyJWT |
| **3 – Web frameworks** | **Flask** REST API in `api/` (app factory, blueprints, decorators, error handlers, CORS, OpenAPI docs with flask-smorest) · **Streamlit** in `ui/web_app.py` + `ui/components/*` (session state, forms, file upload, maps, data editor, downloads, theming) |
| **4 – File handling & pandas** | `analytics/data_handler.py`: `pandas.read_sql`, SQLAlchemy, `io.StringIO`/`BytesIO`, CSV + XML export with `xml.etree.ElementTree`, XML import · `scripts/import_csv_to_db.py` · `analytics/pandas_engine.py`: typing, missing values, boolean filtering, `set_index`/`.loc`, `groupby`, **MultiIndex**, `unstack`, `resample`, `join` |
| **5 – NumPy & charts** | `analytics/numpy_stats.py`: total/mean/median/std/percentiles/CV, monthly spend std, recovery rate, response times, growth rates, z-score outliers, moving average; matplotlib + seaborn charts with transparent dark backgrounds – served to the UIs by `GET /analytics/summary` |

---

## Project files

```
pawconnect_project/
├── main.py                 launcher (--all / --api / --desktop / --reset-data / --test)
├── config.py               every setting and every colour in one place (reads .env)
├── check_setup.py          checks Python, libraries, database, e-mail (--send-test)
├── .env.example            all settings with comments (copy to .env)
├── docker-compose.yml      optional PostgreSQL
├── alembic.ini
├── api/         __init__ (create_app) · client.py · security.py · errors.py · schemas.py · blueprints/
├── core/        models.py · validators.py · workflows.py
├── db/          engine.py · tables.py · migrations/
├── services/    email_service · payment_razorpay · api_service · notification_service · sms_service (stub)
├── analytics/   data_handler.py · pandas_engine.py · numpy_stats.py · sample_data.py
├── ui/          web_app.py · api_session.py · styles.py · desktop_gui.py · components/<role>_dashboard.py
├── scripts/     import_csv_to_db.py
├── data/        pawconnect.db · old CSV files (import source) · uploads/ · exports/ · outbox.log
└── tests/       database, API, e-mail, workflow, model, validator, analytics and UI tests
```

---

## Security notes

- Passwords: salted PBKDF2-SHA256 (200,000 iterations), compared with `hmac.compare_digest`; never shown or exported.
- Sign-in tokens: JWT (HS256), 1-hour expiry; roles are re-read from the database on every request.
- Login: 5 failed attempts per minute per IP → `429`. Every attempt is in the audit log.
- One-time codes: 6 digits, only a hash is stored, expire after 5 minutes, 3 tries, single use, one per
  30 s and 5 per hour per e-mail address. Forgot-password answers the same whether or not the account exists.
- Card numbers and CVVs are validated (regex + Luhn + expiry) and **never stored**; Razorpay cards never reach PawConnect.
- Payments and webhooks are trusted only after their HMAC signature is verified.
- CORS allows only the Streamlit origin. Secrets come from `.env`, which is git-ignored.
- Free text is stripped of HTML and protected against CSV formula injection; e-mail templates escape all user text.

---

## Troubleshooting

- **`streamlit: command not found`** – activate the venv (`source venv/bin/activate`) or use `python main.py`.
- **"Can't reach the PawConnect API"** – start it with `python main.py --api`, use `--all`, or run with `PAWCONNECT_MODE=local`.
- **Port in use** – `python main.py --all --port 8502 --api-port 5050`.
- **Signed out after restarting the API** – set `PAWCONNECT_JWT_SECRET` in `.env`.
- **Desktop console won't open on macOS** – make sure you ran `pip install -r requirements.txt` inside the venv.
- **Location looks approximate** – without internet the app uses an offline pincode-zone table.
- **Messed up the data** – `python main.py --reset-data`.

## Ideas for later

SMS through Twilio/MSG91, PDF receipts, image classification of injury photos, nearest-rescuer routing,
and deploying the API behind gunicorn + nginx.
