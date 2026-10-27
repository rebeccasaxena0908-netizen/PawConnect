"""
E-mail notifications (Unit 2: smtplib, email.message, threads).

Every message PawConnect sends goes through send_email():
  * SMTP with STARTTLS (Gmail by default – see README for the app password),
    a 10-second timeout, plain-text + HTML alternatives in one EmailMessage;
  * returns {"ok": bool, "status": str, "error": str} and NEVER raises, so a
    mail problem can't crash the app;
  * writes one status line to data/outbox.log (recipient, subject, result) –
    never the message body, so OTP codes and passwords are never logged.

When SMTP_USER / SMTP_PASSWORD are not set (config.EMAIL_ENABLED is False) the
message is only "simulated": the status line is written and nothing is sent.

Most e-mails are sent in the background (ThreadPoolExecutor, 2 workers) so the
app never waits for the mail server. OTP e-mails wait for the result (up to 10 s)
so the user can be told "could not send, try again".
"""
from __future__ import annotations

import json
import smtplib
import threading
import ssl
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures import wait
from email.message import EmailMessage
from html import escape

import config
from services.notification_service import build_receipt, format_inr

SEND_TIMEOUT = 10                      # seconds, for the SMTP connection and for waiting on OTP mails
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pawconnect-mail")
_pending: set[Future] = set()                 # background sends that haven't finished yet
_pending_lock = threading.Lock()


# ======================================================================= sending
def _outbox(to: str, subject: str, status: str) -> None:
    """One status line per e-mail – never the body (it may contain an OTP)."""
    config.OUTBOX_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = {"channel": "email", "to": to, "subject": subject, "status": status,
            "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    with config.OUTBOX_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def _friendly(error: Exception) -> str:
    """Turn SMTP exceptions into a hint a student can act on (no secrets in it)."""
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return ("SMTP sign-in failed – check SMTP_USER and use a Gmail *app password* "
                "(Application-specific password required).")
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return "The mail server refused this address."
    if isinstance(error, (TimeoutError, ConnectionError, OSError)) and not isinstance(error, smtplib.SMTPException):
        return "Couldn't reach the mail server (network blocked or offline)."
    return f"Mail server error ({error.__class__.__name__})."


def send_email(to: str, subject: str, text_body: str, html_body: str | None = None) -> dict:
    """Send one e-mail now. Returns {"ok", "status", "error"}; never raises."""
    if not config.EMAIL_ENABLED:
        _outbox(to, subject, "simulated (SMTP not configured)")
        return {"ok": True, "status": "simulated", "error": ""}
    message = EmailMessage()
    message["From"] = config.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=SEND_TIMEOUT) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(message)
    except Exception as error:          # noqa: BLE001 – any failure becomes ok=False
        reason = _friendly(error)
        _outbox(to, subject, f"failed: {reason}")
        return {"ok": False, "status": "failed", "error": reason}
    _outbox(to, subject, "sent")
    return {"ok": True, "status": "sent", "error": ""}


def send_in_background(to: str, subject: str, text_body: str, html_body: str | None = None) -> Future:
    """Queue the e-mail on the 2-worker pool and return at once."""
    future = _pool.submit(send_email, to, subject, text_body, html_body)
    with _pending_lock:
        _pending.add(future)
    future.add_done_callback(lambda done: _pending.discard(done))
    return future


def flush(timeout: float = SEND_TIMEOUT) -> None:
    """Wait until every queued e-mail has been handled (used by tests and check_setup)."""
    with _pending_lock:
        waiting = list(_pending)
    wait(waiting, timeout=timeout)


def wait_for(future: Future, timeout: float = SEND_TIMEOUT) -> dict:
    try:
        return future.result(timeout=timeout)
    except FutureTimeout:
        return {"ok": False, "status": "failed", "error": "The mail server took too long to answer."}


# ======================================================================= HTML layout (table based, inline CSS – Gmail-safe)
def _layout(heading: str, body_html: str, footer: str = "") -> str:
    c = config.COLORS
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:{c['bg']};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{c['bg']};padding:28px 12px;">
 <tr><td align="center">
  <table role="presentation" width="560" cellpadding="0" cellspacing="0"
         style="max-width:560px;width:100%;background:{c['surface']};border:1px solid {c['border']};border-radius:18px;">
   <tr><td style="padding:26px 30px 6px;font-family:Georgia,'Times New Roman',serif;font-size:13px;letter-spacing:2px;
                  text-transform:uppercase;color:{c['accent']};">🐾 {escape(config.APP_NAME)}</td></tr>
   <tr><td style="padding:4px 30px 8px;font-family:Georgia,'Times New Roman',serif;font-size:24px;font-weight:bold;
                  color:{c['text']};">{escape(heading)}</td></tr>
   <tr><td style="padding:6px 30px 26px;font-family:'Nunito Sans',Arial,sans-serif;font-size:15px;line-height:1.6;
                  color:{c['text']};">{body_html}</td></tr>
   <tr><td style="padding:16px 30px 22px;border-top:1px solid {c['border']};font-family:Arial,sans-serif;font-size:12px;
                  line-height:1.5;color:{c['muted']};">{footer or escape(config.ORG_NAME)}</td></tr>
  </table>
 </td></tr>
</table></body></html>"""


def _p(text_html: str, muted: bool = False) -> str:
    color = config.COLORS["muted"] if muted else config.COLORS["text"]
    return f'<p style="margin:0 0 12px;color:{color};">{text_html}</p>'


def _badge(text: str, color: str) -> str:
    return (f'<span style="display:inline-block;padding:4px 12px;border-radius:999px;border:1px solid {color};'
            f'color:{color};font-weight:bold;font-size:13px;">{escape(text)}</span>')


# ======================================================================= templates (each returns subject, text, html)
def otp_email(code: str, purpose: str = "sign up") -> tuple[str, str, str]:
    minutes = config.OTP_TTL_SECONDS // 60
    action = "create your account" if purpose == "sign up" else "reset your password"
    subject = f"Your {config.APP_NAME} verification code"          # the code is NOT in the subject
    text = (f"Your {config.APP_NAME} code to {action} is: {code}\n\n"
            f"It expires in {minutes} minutes and can be used once.\n"
            "If you didn't request this, you can safely ignore this e-mail.")
    c = config.COLORS
    spaced = " ".join(code)
    body = (_p(f"Use this code to {escape(action)}:")
            + f'<div style="margin:18px 0;padding:18px;background:{c["raised"]};border:1px solid {c["border"]};'
              f'border-radius:14px;text-align:center;font-family:Georgia,serif;font-size:34px;font-weight:bold;'
              f'letter-spacing:10px;color:{c["accent"]};">{escape(spaced)}</div>'
            + _p(f"It expires in <b>{minutes} minutes</b> and can be used once.")
            + _p("If you didn't request this, you can safely ignore this e-mail.", muted=True))
    return subject, text, _layout("Your verification code", body)


def welcome_email(name: str, role: str) -> tuple[str, str, str]:
    subject = f"Welcome to {config.APP_NAME}, {name.split()[0]}!"
    text = (f"Hi {name},\n\nYour {role} account is ready. Thank you for joining a network that gives "
            "stray animals a second chance.\n\n– The PawConnect team")
    body = (_p(f"Hi {escape(name)},")
            + _p(f"Your {_badge(role, config.COLORS['accent2'])} account is ready.")
            + _p("Thank you for joining a network that gives stray animals a second chance – "
                 "every report, rescue, rupee and adoption counts."))
    return subject, text, _layout("Welcome to the pack 🐾", body)


def receipt_email(donation: dict) -> tuple[str, str, str]:
    c = config.COLORS
    plain = build_receipt(donation)
    subject = f"{config.APP_NAME} receipt {donation['transaction_id']}"
    rows = [("Receipt / transaction ID", donation["transaction_id"]), ("Date", donation["timestamp"]),
            ("Amount", format_inr(donation["amount"])), ("Fund", donation["contribution_type"])]
    if donation.get("case_id"):
        rows.append(("Rescue case", donation["case_id"]))
    rows += [("Paid by", f"{donation['method']} ({donation['masked_account']})"),
             ("Gateway reference", donation["payment_ref"])]
    table = "".join(
        f'<tr><td style="padding:7px 0;color:{c["muted"]};font-size:14px;">{escape(k)}</td>'
        f'<td style="padding:7px 0;text-align:right;font-weight:bold;color:{c["text"]};font-size:14px;">'
        f"{escape(str(v))}</td></tr>" for k, v in rows)
    sandbox = donation.get("method") in ("UPI", "Card")
    body = (_p(f"Thank you, {escape(donation['donor_name'])}! We received your gift.")
            + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
              f'style="margin:8px 0 16px;border-top:1px solid {c["border"]};border-bottom:1px solid {c["border"]};">{table}</table>'
            + _p(f"80G registration: {escape(config.ORG_80G_NO)}. Donations may be eligible for deduction "
                 "under Section 80G of the Income Tax Act.", muted=True)
            + (_p("<b>Sandbox payment</b> – this is a student project; no real money was charged.", muted=True)
               if sandbox else _p("Razorpay TEST mode payment – no real money was charged.", muted=True)))
    return subject, plain, _layout("Donation receipt", body)


def case_update_email(name: str, case_id: str, status: str) -> tuple[str, str, str]:
    subject = f"Your report {case_id} is now {status}"
    text = (f"Hi {name},\n\nUpdate on your SOS {case_id}: the animal is now '{status}'.\n"
            "Thank you for reporting – you made this rescue possible.")
    body = (_p(f"Hi {escape(name)},")
            + _p(f"Your report <b>{escape(case_id)}</b> is now {_badge(status, config.COLORS['accent2'])}")
            + _p("Thank you for reporting – you made this rescue possible."))
    return subject, text, _layout("Rescue update", body)


def adoption_email(name: str, application_id: str, animal_name: str, status: str) -> tuple[str, str, str]:
    messages = {
        "Pre-Approved": ("You're pre-approved! 🎉", "The shelter will call you to arrange a home visit.",
                         config.COLORS["success"]),
        "Approved": ("Adoption approved! 🏡", "Welcome home – the shelter will contact you about the hand-over.",
                     config.COLORS["success"]),
        "Rejected": ("About your application", "This time the shelter couldn't approve it. Thank you for caring – "
                     "other animals may be a better match.", config.COLORS["danger"]),
    }
    heading, line, colour = messages.get(status, ("Application update", "", config.COLORS["accent2"]))
    subject = f"Adoption application {application_id}: {status}"
    text = f"Hi {name},\n\nYour application {application_id} for {animal_name} is {status}.\n{line}"
    body = (_p(f"Hi {escape(name)},")
            + _p(f"Your application <b>{escape(application_id)}</b> for <b>{escape(animal_name)}</b> is "
                 f"{_badge(status, colour)}")
            + _p(escape(line)))
    return subject, text, _layout(heading, body)


# ======================================================================= what the workflows call
def send_otp(to: str, code: str, purpose: str = "sign up") -> dict:
    """OTP e-mails wait for the answer (max 10 s) so the user can be told if it failed."""
    return wait_for(send_in_background(to, *otp_email(code, purpose)))


def send_welcome(to: str, name: str, role: str) -> Future:
    return send_in_background(to, *welcome_email(name, role))


def send_receipt(donation: dict) -> str:
    """E-mail the receipt in the background; return the plain-text receipt for the screen."""
    subject, text, html_body = receipt_email(donation)
    if donation.get("donor_email"):
        send_in_background(donation["donor_email"], subject, text, html_body)
    return text


def send_case_update(to: str, name: str, case_id: str, status: str) -> Future:
    return send_in_background(to, *case_update_email(name, case_id, status))


def send_adoption_decision(to: str, name: str, application_id: str, animal_name: str, status: str) -> Future:
    return send_in_background(to, *adoption_email(name, application_id, animal_name, status))
