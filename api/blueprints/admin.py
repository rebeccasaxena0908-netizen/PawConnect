"""Inventory, users, analytics, audit log, exports and the health check."""
import pandas as pd

import config
from flask import Response, g
from flask_smorest import Blueprint

from analytics import numpy_stats as ns
from analytics import pandas_engine as pe
from api.schemas import EmailTestIn, ExportQuery, InventoryIn, RoleQuery
from api.security import ApiError, require_auth, require_permission
from api.util import plain, records, series_points
from core import workflows as wf

inventory = Blueprint("inventory", __name__, url_prefix="/inventory", description="Beds and medical stock")
users = Blueprint("users", __name__, url_prefix="/users", description="Accounts (admin)")
analytics = Blueprint("analytics", __name__, url_prefix="/analytics", description="Statistics for the dashboards")
admin = Blueprint("admin", __name__, url_prefix="/admin", description="Audit log, exports and backups")
health = Blueprint("health", __name__, description="Is the API up?")


# ======================================================================= inventory
@inventory.route("", methods=["GET"])
@inventory.response(200)
@require_permission("manage_inventory")
def get_inventory():
    stock = wf.list_inventory()
    low = set(pe.low_stock(stock)["item_id"])
    return [{**row, "low_stock": row["item_id"] in low} for row in records(stock)]


@inventory.route("", methods=["PUT"])
@inventory.arguments(InventoryIn)
@inventory.response(200)
@require_permission("manage_inventory")
def put_inventory(body):
    """Replace the whole stock list (rows without item_id get a new one)."""
    frame = pd.DataFrame(body["items"], columns=["item_id", "item", "category", "quantity", "unit",
                                                 "reorder_level"])
    count = wf.save_inventory(g.user, frame.assign(updated_at=""))
    return {"saved": count, "items": records(wf.list_inventory())}


# ======================================================================= users
@users.route("", methods=["GET"])
@users.arguments(RoleQuery, location="query")
@users.response(200)
@require_permission("manage_users")
def list_users(query):
    """Every account (never the password hashes). Filter with ?role=Rescuer."""
    return records(wf.list_users(query["role"]))


@users.route("/rescuers", methods=["GET"])
@users.response(200)
@require_permission("assign_case")
def rescuers():
    """{user_id: "Name (pincode)"} for the assign-a-rescuer drop-downs."""
    return wf.rescuer_choices()


# ======================================================================= analytics
@analytics.route("/summary", methods=["GET"])
@analytics.response(200)
@require_auth
def summary():
    """
    Everything the dashboards chart: money statistics (NumPy mean / std ...),
    recovery rate, response times and monthly series. All anonymous – no donor names.
    """
    donations = pe.clean_donations(wf.list_donations())
    allocations = pe.clean_allocations(wf.list_allocations())
    cases = pe.clean_cases(wf.list_cases())
    monthly = pe.monthly_donations(donations)
    spending = pe.monthly_expenditure(allocations)
    in_use, beds = pe.bed_availability(wf.list_inventory(), cases)
    return {
        "money": {k: plain(v) for k, v in ns.financial_summary(donations["amount"]).items()},
        "recovery_rate": round(ns.recovery_rate(cases["status"].astype(str)), 1),
        "response_hours": {k: round(v, 2) for k, v in
                           ns.response_time_stats(pe.response_times_hours(cases)).items()},
        "monthly_spend_std": round(ns.monthly_std(spending), 2),
        "monthly_donations": series_points(monthly, "amount"),
        "monthly_expenditure": series_points(spending, "amount"),
        "growth_percent": [plain(x) for x in ns.growth_rates(monthly.values)],
        "utilization": {k: plain(v) for k, v in pe.utilization_by_purpose(allocations).items()},
        "by_fund": records(pe.donations_by_type(donations).reset_index()),
        "cases_by_status": {k: int(v) for k, v in pe.cases_by_status(cases).items()},
        "donation_amounts": [plain(x) for x in donations["amount"]],
        "open_cases": int((cases["status"] != "Recovered").sum()),
        "waiting_cases": int((cases["status"] == "Reported").sum()),
        "helped": int((cases["status"] != "Reported").sum()),
        "recovered": int((cases["status"] == "Recovered").sum()),
        "adopted": int((wf.list_animals()["status"] == "Adopted").sum()),
        "beds": {"in_use": in_use, "total": beds},
    }


@analytics.route("/impact", methods=["GET"])
@analytics.doc(security=[])
@analytics.response(200)
def impact():
    """Three public numbers for the sign-in page (no sign-in needed, nothing personal)."""
    cases, animals = wf.list_cases(), wf.list_animals()
    waiting = animals[animals["status"] == "Available"].tail(8)
    return {"helped": int((cases["status"] != "Reported").sum()),
            "recovered": int((cases["status"] == "Recovered").sum()),
            "adopted": int((animals["status"] == "Adopted").sum()),
            "in_treatment": int(cases["status"].isin(["Assigned", "In Transit", "Sheltered/In Treatment"]).sum()),
            "available": int((animals["status"] == "Available").sum()),
            # a few animals waiting for a home – no personal data, just the catalogue card
            "spotlight": records(waiting[["name", "species", "breed", "age_years", "gender", "temperament"]])}


# ======================================================================= admin tools
@admin.route("/audit", methods=["GET"])
@admin.response(200)
@require_permission("view_audit_log")
def audit():
    """Audit events, newest first."""
    return records(wf.audit_log(g.user))


@admin.route("/audit.xml", methods=["GET"])
@require_permission("view_audit_log")
def audit_xml():
    """The audit trail as audit_logs.xml (generated from the database)."""
    return Response(wf.audit_log_xml(g.user), mimetype="application/xml",
                    headers={"Content-Disposition": "attachment; filename=audit_logs.xml"})


@admin.route("/tables/<name>", methods=["GET"])
@admin.response(200)
@require_permission("export_data")
def table(name):
    """Any table as JSON rows (used by the data-quality tools)."""
    return records(wf.any_table(g.user, name))


@admin.route("/export/<name>", methods=["GET"])
@admin.arguments(ExportQuery, location="query")
@require_permission("export_data")
def export(query, name):
    """Download a table as CSV (?format=csv) or structured XML (?format=xml)."""
    kind = query["format"]
    data = wf.export_table(g.user, name, kind)
    return Response(data, mimetype="text/csv" if kind == "csv" else "application/xml",
                    headers={"Content-Disposition": f"attachment; filename={name}.{kind}"})


@admin.route("/backup", methods=["POST"])
@admin.response(201)
@require_permission("export_data")
def backup():
    """Write CSV + XML copies of every table into data/exports/<timestamp>/ on the server."""
    written = wf.create_backup(g.user)
    return {"folder": str(written[0].parent), "files": len(written)}


@admin.route("/email", methods=["GET"])
@admin.response(200)
@require_permission("manage_users")
def email_settings():
    """Is real e-mail on? Plus the last 15 status lines from the outbox (never bodies or codes)."""
    return wf.email_status(g.user)


@admin.route("/email/test", methods=["POST"])
@admin.arguments(EmailTestIn)
@admin.response(200)
@require_permission("manage_users")
def email_test(body):
    """Send one test e-mail now and report exactly what the mail server said."""
    return wf.send_test_email(g.user, body["to"])


# ======================================================================= health
@health.route("/health", methods=["GET"])
@health.doc(security=[])
@health.response(200)
def health_check():
    """200 when the API and its database are working."""
    from flask import current_app
    from sqlalchemy import text
    from db.engine import reading
    try:
        with reading() as conn:
            conn.execute(text("SELECT 1"))
        database = "ok"
    except Exception as error:      # noqa: BLE001 – report any database problem
        raise ApiError(503, "The database is not reachable.", [error.__class__.__name__]) from None
    return {"status": "ok", "service": "PawConnect API", "database": database,
            "gateway": "razorpay" if current_app.extensions["pawconnect"]["razorpay"] else "sandbox",
            "email": "smtp" if config.EMAIL_ENABLED else "simulated"}
