"""Sign in, sign up (OTP by e-mail), forgot password and who-am-I."""
import time

from flask import current_app, g
from flask_smorest import Blueprint

from api.schemas import ForgotPasswordIn, LoginIn, RegisterStartIn, RegisterVerifyIn, ResetPasswordIn
from api.security import ApiError, client_ip, create_token, require_auth
from analytics import data_handler as dh
from config import JWT_EXPIRY_SECONDS, OTP_TTL_SECONDS, SHOW_OTP_ON_SCREEN
from core import validators as v
from core import workflows as wf

blp = Blueprint("auth", __name__, description="Sign in, sign up (OTP by e-mail), password reset, current user")


def _state():
    return current_app.extensions["pawconnect"]


def _token_reply(user):
    return {"access_token": create_token(user), "token_type": "Bearer",
            "expires_in": JWT_EXPIRY_SECONDS, "user": user.public_dict()}


def _code_reply(message: str, email: str, code: str | None) -> dict:
    reply = {"message": message, "email": email, "masked_email": v.mask_email(email),
             "expires_in": OTP_TTL_SECONDS}
    if SHOW_OTP_ON_SCREEN and code:
        reply["demo_otp"] = code       # demo mode only: SMTP isn't configured, so nothing was really e-mailed
    return reply


@blp.route("/auth/login", methods=["POST"])
@blp.arguments(LoginIn)
@blp.doc(security=[])
@blp.response(200)
def login(body):
    """Sign in with e-mail or mobile + password. Returns a 1-hour JWT."""
    limiter, ip = _state()["login_failures"], client_ip()
    limiter.check(ip, "failed sign-in attempts")
    user = wf.authenticate(body["identifier"], body["password"])
    if user is None:
        limiter.hit(ip)
        raise ApiError(401, "That e-mail/mobile and password don't match.")
    return _token_reply(user)


@blp.route("/auth/logout", methods=["POST"])
@blp.response(200)
@require_auth
def logout():
    """Record the sign-out in the audit log (the token simply expires)."""
    dh.log_event(g.user.user_id, g.user.role, "LOGOUT", f"{g.user.name} signed out")
    return {"message": "Signed out."}


@blp.route("/me", methods=["GET"])
@blp.response(200)
@require_auth
def me():
    """The signed-in user and their permissions."""
    return {**g.user.public_dict(), "permissions": sorted(g.user.permissions),
            "dashboard_title": g.user.dashboard_title}


# ======================================================================= sign up
@blp.route("/auth/register/start", methods=["POST"])
@blp.arguments(RegisterStartIn)
@blp.doc(security=[])
@blp.response(200)
def register_start(body):
    """Check the sign-up form and e-mail a 6-digit code. Mobile is optional. 503 if the e-mail can't be sent."""
    state = _state()
    state["otp_sends"].check(client_ip(), "OTP requests")
    clean = wf.check_registration(body["name"], body["email"], body["mobile"], body["role"],
                                  body["pincode"], body["password"], body.get("confirm"))
    state["otp_sends"].hit(client_ip())
    code = wf.send_signup_otp(state["otp"], clean["email"])     # 30 s cooldown, 5 per hour per address
    # The password waits in server memory only until the code is verified (max 5 minutes).
    state["pending"][clean["email"]] = {**clean, "password": body["password"],
                                        "expires": time.time() + OTP_TTL_SECONDS}
    return _code_reply(f"We e-mailed a 6-digit code to {v.mask_email(clean['email'])}.", clean["email"], code)


@blp.route("/auth/register/verify", methods=["POST"])
@blp.arguments(RegisterVerifyIn)
@blp.doc(security=[])
@blp.response(201)
def register_verify(body):
    """Check the e-mailed code and create the account. Returns a JWT so the new user is signed in."""
    state = _state()
    state["otp_verifies"].check(client_ip(), "OTP attempts")
    state["otp_verifies"].hit(client_ip())
    email = v.normalize("email", body["email"])
    pending = state["pending"].get(email)
    if pending is None or pending["expires"] < time.time():
        state["pending"].pop(email, None)
        raise ApiError(404, "No sign-up is waiting for this e-mail. Start again.")
    wf.verify_signup_otp(state["otp"], email, body["otp"])
    state["pending"].pop(email, None)
    user = wf.register_user(pending["name"], pending["email"], pending["mobile"], pending["role"],
                            pending["pincode"], pending["password"])
    return _token_reply(user)


# ======================================================================= forgot password
@blp.route("/auth/password/forgot", methods=["POST"])
@blp.arguments(ForgotPasswordIn)
@blp.doc(security=[])
@blp.response(200)
def forgot_password(body):
    """E-mail a reset code. The answer is the same whether or not the account exists."""
    state = _state()
    state["otp_sends"].check(client_ip(), "OTP requests")
    state["otp_sends"].hit(client_ip())
    email = v.normalize("email", body["email"])
    code = wf.request_password_reset(state["otp"], email)
    return _code_reply(f"If an account uses {v.mask_email(email)}, we e-mailed it a 6-digit code.", email, code)


@blp.route("/auth/password/reset", methods=["POST"])
@blp.arguments(ResetPasswordIn)
@blp.doc(security=[])
@blp.response(200)
def reset_password(body):
    """Check the code and set the new password (same strength rules as sign-up)."""
    state = _state()
    state["otp_verifies"].check(client_ip(), "OTP attempts")
    state["otp_verifies"].hit(client_ip())
    wf.reset_password(state["otp"], body["email"], body["otp"], body["new_password"], body.get("confirm"))
    return {"message": "Password changed. You can sign in now."}
