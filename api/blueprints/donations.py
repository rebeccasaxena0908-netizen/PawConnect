"""Donations, receipts and payments (sandbox gateway by default, Razorpay test mode when configured)."""
import json
import time

import jwt
from flask import current_app, g, request, url_for
from flask_smorest import Blueprint

from api.schemas import CheckoutVerifyIn, DonationIn
from api.security import ApiError, require_auth, require_permission
from api.util import records
from config import APP_NAME, COLORS, PAYMENT_SECRET
from core import workflows as wf
from services.api_service import PaymentGatewaySimulator
from services.payment_razorpay import parse_webhook_event

blp = Blueprint("donations", __name__, url_prefix="/donations", description="Donations and receipts")
payments = Blueprint("payments", __name__, url_prefix="/payments", description="Payment gateway callbacks")

CHECKOUT_LINK_SECONDS = 900


def _razorpay():
    return current_app.extensions["pawconnect"]["razorpay"]


def _own_or_admin(row: dict) -> None:
    if row["donor_id"] != g.user.user_id and not g.user.can("export_data"):
        raise ApiError(403, "You can only see your own donations.")


# ======================================================================= donations
@blp.route("", methods=["POST"])
@blp.arguments(DonationIn)
@blp.response(201)
@require_permission("donate")
def donate(body):
    """
    Give money. UPI / Card use the sandbox gateway and finish at once (card data
    is checked, never stored). "Razorpay" creates a real test-mode order and
    returns a checkout link; the donation stays Pending until Razorpay confirms.
    """
    if body["method"] == "Razorpay":
        gateway = _razorpay()
        if gateway is None:
            raise ApiError(422, "Razorpay isn't set up on this server.",
                           ["Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET, or pay by UPI/card (sandbox)."])
        tx, order = wf.start_online_donation(g.user, body["amount"], body["contribution_type"], gateway,
                                             body["case_id"])
        token = jwt.encode({"tx": tx.transaction_id, "exp": int(time.time()) + CHECKOUT_LINK_SECONDS},
                           current_app.config["JWT_SECRET"], algorithm="HS256")
        link = url_for("payments.checkout_page", transaction_id=tx.transaction_id, t=token, _external=True)
        return {"donation": tx.to_dict(), "receipt": "",
                "checkout": {"key_id": gateway.key_id, "order_id": order["id"], "amount": order["amount"],
                             "currency": order["currency"], "url": link}}
    details = {k: body[k] for k in ("upi", "card_number", "expiry", "cvv", "card_name")}
    tx, receipt = wf.make_donation(g.user, body["amount"], body["contribution_type"], body["method"],
                                   details, body["case_id"])
    return {"donation": tx.to_dict(), "receipt": receipt}


@blp.route("", methods=["GET"])
@blp.response(200)
@require_auth
def list_donations():
    """Donors get their own donations, admins get every donation."""
    if g.user.can("export_data"):
        return records(wf.list_donations())
    if not g.user.can("view_own_donations"):
        raise ApiError(403, f"{g.user.role}s don't have donations.")
    return records(wf.list_donations(g.user))


@blp.route("/<transaction_id>", methods=["GET"])
@blp.response(200)
@require_auth
def get_donation(transaction_id):
    row = wf.get_donation(transaction_id)
    _own_or_admin(row)
    return row


@blp.route("/<transaction_id>/receipt", methods=["GET"])
@blp.response(200)
@require_auth
def receipt(transaction_id):
    """The plain-text receipt (with the 80G note)."""
    row = wf.get_donation(transaction_id)
    _own_or_admin(row)
    if row["status"] != "Success":
        raise ApiError(409, f"No receipt yet – this donation is {row['status']}.")
    return {"transaction_id": transaction_id, "receipt": wf.donation_receipt(transaction_id)}


# ======================================================================= payments
@payments.route("/config", methods=["GET"])
@payments.doc(security=[])
@payments.response(200)
def payment_config():
    """Which gateway is active. The key id is public by design; the secret never leaves the server."""
    gateway = _razorpay()
    return {"gateway": "razorpay" if gateway else "sandbox",
            "razorpay_key_id": gateway.key_id if gateway else None}


@payments.route("/checkout/<transaction_id>", methods=["GET"])
@payments.doc(security=[])
def checkout_page(transaction_id):
    """HTML page that opens Razorpay Checkout for a Pending donation (link valid 15 minutes)."""
    try:
        claims = jwt.decode(request.args.get("t", ""), current_app.config["JWT_SECRET"], algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise ApiError(403, "This payment link is invalid or has expired.") from None
    if claims.get("tx") != transaction_id or _razorpay() is None:
        raise ApiError(403, "This payment link is invalid.")
    row = wf.get_donation(transaction_id)
    if row["status"] != "Pending":
        return f"<p>This donation is already {row['status']}. You can close this tab.</p>"
    options = {
        "key": _razorpay().key_id, "order_id": row["payment_ref"], "currency": "INR",
        "amount": int(round(float(row["amount"]) * 100)), "name": APP_NAME,
        "description": row["contribution_type"], "prefill": {"name": row["donor_name"],
                                                             "email": row["donor_email"]},
        "theme": {"color": COLORS["accent"]},
    }
    verify_url = url_for("payments.checkout_verify")
    page = CHECKOUT_HTML.replace("__OPTIONS__", json.dumps(options)).replace("__VERIFY__", verify_url)
    for key, value in COLORS.items():                  # colours come from config.COLORS
        page = page.replace(f"__{key.upper()}__", value)
    return page


@payments.route("/razorpay/verify", methods=["POST"])
@payments.arguments(CheckoutVerifyIn)
@payments.doc(security=[])
@payments.response(200)
def checkout_verify(body):
    """Razorpay Checkout's success callback. Trusted only if the HMAC signature matches."""
    gateway = _razorpay()
    if gateway is None or not gateway.verify_checkout(body["razorpay_order_id"], body["razorpay_payment_id"],
                                                      body["razorpay_signature"]):
        raise ApiError(400, "Payment signature could not be verified. Nothing was recorded.")
    row = wf.settle_online_payment(body["razorpay_order_id"], body["razorpay_payment_id"], True)
    if row is None:
        raise ApiError(404, "No donation is waiting for this order.")
    return {"transaction_id": row["transaction_id"], "status": row["status"]}


@payments.route("/webhook", methods=["POST"])
@payments.doc(security=[])
@payments.response(200)
def webhook():
    """
    Razorpay server-to-server webhook. The X-Razorpay-Signature header must be
    HMAC-SHA256(raw body, webhook secret) – checked BEFORE the JSON is even parsed.
    Without Razorpay keys the sandbox secret is used, so the flow can be demoed offline.
    """
    raw = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature", "")
    gateway = _razorpay()
    if gateway is not None:
        trusted = gateway.verify_webhook(raw, signature)
    else:
        trusted = PaymentGatewaySimulator(secret=PAYMENT_SECRET).verify_signature(raw.decode("utf-8", "replace"),
                                                                                  signature)
    if not trusted:
        raise ApiError(400, "Invalid webhook signature.")
    try:
        event = json.loads(raw)
    except ValueError:
        raise ApiError(400, "Webhook body is not JSON.") from None
    parsed = parse_webhook_event(event)
    if parsed is None and gateway is None:          # sandbox payload shape
        payment = event.get("payload", {}).get("payment", {})
        parsed = (payment.get("order_id", ""), payment.get("id", ""), payment.get("status") == "captured")
    if parsed is None:
        return {"handled": False, "event": event.get("event")}
    order_id, payment_id, succeeded = parsed
    row = wf.settle_online_payment(order_id, payment_id, succeeded, source="webhook")
    return {"handled": row is not None, "status": row["status"] if row else None}


CHECKOUT_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PawConnect – secure payment</title>
<style>
 body{margin:0;min-height:100vh;display:grid;place-items:center;background:__BG__;color:__TEXT__;
      font-family:'Nunito Sans',system-ui,-apple-system,Segoe UI,sans-serif}
 .card{background:__SURFACE__;border:1px solid __BORDER__;border-radius:18px;padding:28px 32px;max-width:420px;text-align:center}
 button{background:linear-gradient(135deg,__ACCENT_FILL__,__ACCENT_FILL_DEEP__);color:__ON_ACCENT__;border:0;border-radius:12px;
        padding:12px 22px;font-weight:700;font-size:15px;cursor:pointer}
 button:focus-visible{outline:3px solid __ACCENT__;outline-offset:2px}
 .muted{color:__MUTED__;font-size:14px}
</style></head>
<body><div class="card"><h2>🐾 PawConnect</h2>
<p id="msg" class="muted">Razorpay TEST mode – use a test card or UPI <b>success@razorpay</b>.</p>
<button id="pay">Pay securely</button></div>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<script>
const options = __OPTIONS__;
const msg = document.getElementById("msg");
options.handler = async function (r) {
  msg.textContent = "Verifying payment…";
  const res = await fetch("__VERIFY__", {method: "POST", headers: {"Content-Type": "application/json"},
                                         body: JSON.stringify(r)});
  const data = await res.json();
  msg.textContent = res.ok ? "✅ Payment confirmed (" + data.transaction_id + "). You can close this tab and refresh PawConnect."
                           : "❌ " + data.error;
};
options.modal = {ondismiss: () => { msg.textContent = "Payment cancelled. Nothing was charged."; }};
document.getElementById("pay").onclick = () => new Razorpay(options).open();
</script></body></html>"""
