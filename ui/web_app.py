"""
PawConnect web app (Unit 3: Streamlit).

Run from the project folder:   python main.py --all     (API + web app)
                       or:     python main.py           (web app; uses the API if it is running,
                                                         otherwise runs it in-process)

The web app never touches the database: every read and write goes through
PawConnectClient (api/client.py) → the Flask REST API → core/workflows.py.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from config import (APP_NAME, APP_TAGLINE, OTP_RESEND_COOLDOWN, OTP_TTL_SECONDS,  # noqa: E402
                    SELF_REGISTER_ROLES)
from core.models import User  # noqa: E402
from ui.api_session import ApiError, AuthError, api, current_user, sign_in, sign_out  # noqa: E402
from ui.components import (admin_dashboard, adopter_dashboard, citizen_dashboard,  # noqa: E402
                           donor_dashboard, rescuer_dashboard)
from ui.styles import esc, hero, inject_css, pill, show_problems, theme_toggle  # noqa: E402

DASHBOARDS = {
    "Citizen": citizen_dashboard.render,
    "Adopter": adopter_dashboard.render,
    "Rescuer": rescuer_dashboard.render,
    "Donor": donor_dashboard.render,
    "Admin": admin_dashboard.render,
}
ROLE_BLURBS = {
    "Citizen": "Report injured strays and follow their recovery.",
    "Rescuer": "Pick up SOS calls in your area and update treatment.",
    "Donor": "Fund treatments and see exactly where your money goes.",
    "Adopter": "Give a rescued animal a home.",
}


def _init_state() -> None:
    st.session_state.setdefault("token", None)              # JWT from POST /auth/login
    st.session_state.setdefault("user", None)               # public dict of the signed-in user
    st.session_state.setdefault("pending_signup", None)     # {email, masked_email, ...} while waiting for the code
    st.session_state.setdefault("password_reset", None)     # same, for "Forgot password?"


# ======================================================================= sign in / sign up
def _login_form() -> None:
    with st.form("login"):
        identifier = st.text_input("E-mail or mobile number")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        try:
            sign_in(api().login(identifier, password))
        except ApiError as error:          # 401 wrong password, 429 too many attempts, 503 API down
            show_problems(error)
        else:
            st.rerun()
    _forgot_password()

    _demo_accounts()


def _demo_accounts() -> None:
    """Always-visible card with the demo logins (wraps on a phone instead of scrolling sideways)."""
    accounts = [("Admin", "admin@pawconnect.org", "Admin@123", "accent"),
                ("Rescuer", "arjun.rescue@pawconnect.org", "Rescuer@123", "accent2"),
                ("Donor", "ananya@example.com", "Donor@123", "success"),
                ("Citizen", "karan@example.com", "Citizen@123", "accent3"),
                ("Adopter", "riya@example.com", "Adopter@123", "accent")]
    rows = "".join(f'<div class="pc-demo-row">{pill(role, tone)}<span class="pc-demo-mail">{esc(email)}</span>'
                   f'<code class="pc-demo-pass">{esc(password)}</code></div>' for role, email, password, tone in accounts)
    st.markdown(f'<div class="pc-card"><h4>Try a demo account</h4>{rows}'
                '<div class="meta" style="margin-top:8px">Type one of these above – they are sample data only.</div></div>',
                unsafe_allow_html=True)


def _email_mode() -> str:
    """'smtp' when the server really sends e-mail, 'simulated' otherwise (from GET /health)."""
    if "email_mode" not in st.session_state:
        try:
            st.session_state.email_mode = api().health().get("email", "simulated")
        except ApiError:
            st.session_state.email_mode = "simulated"
    return st.session_state.email_mode


def _demo_code(reply: dict) -> None:
    if reply.get("demo_otp"):
        st.caption(f"Demo mode (e-mail not configured) – your code is **{reply['demo_otp']}**")


def _forgot_password() -> None:
    """Two steps: e-mail a code, then set a new password with it."""
    with st.expander("Forgot password?"):
        reset = st.session_state.get("password_reset")
        if reset is None:
            with st.form("forgot"):
                email = st.text_input("Your account e-mail")
                if st.form_submit_button("E-mail me a code"):
                    try:
                        reply = api().forgot_password(email)
                    except ApiError as error:
                        show_problems(error)
                    else:
                        st.session_state.password_reset = reply
                        st.rerun()
            return
        st.info(reset["message"] + f" It expires in {OTP_TTL_SECONDS // 60} minutes.")
        _demo_code(reset)
        with st.form("reset"):
            code = st.text_input("6-digit code", max_chars=6)
            new = st.text_input("New password", type="password",
                                help="8+ characters with a capital, a small letter, a number and a symbol.")
            confirm = st.text_input("Confirm new password", type="password")
            c1, c2 = st.columns(2)
            save = c1.form_submit_button("Set new password", type="primary")
            cancel = c2.form_submit_button("Cancel")
        if cancel:
            st.session_state.password_reset = None
            st.rerun()
        if save:
            try:
                api().reset_password(reset["email"], code, new, confirm)
            except ApiError as error:
                show_problems(error)
            else:
                st.session_state.password_reset = None
                st.success("Password changed – sign in with the new one.")


def _signup_form() -> None:
    pending = st.session_state.pending_signup
    if pending is None:
        if _email_mode() == "simulated":
            st.info("📭 E-mail is in **demo mode** on this server (SMTP isn't set up in .env), so the code is "
                    "shown here instead of being e-mailed.")
        with st.form("signup"):
            c1, c2 = st.columns(2)
            name = c1.text_input("Full name")
            role = c2.selectbox("I want to join as", SELF_REGISTER_ROLES,
                                format_func=lambda r: f"{r} – {ROLE_BLURBS[r]}")
            email = c1.text_input("E-mail", help="We e-mail you a 6-digit code to confirm it.")
            mobile = c2.text_input("Mobile number (optional)", max_chars=13, placeholder="98XXXXXXXX")
            pincode = c1.text_input("Pincode", max_chars=6)
            password = c2.text_input("Password", type="password",
                                     help="8+ characters with a capital, a small letter, a number and a symbol.")
            confirm = c2.text_input("Confirm password", type="password")
            agree = st.checkbox("I agree that my details are stored to run the rescue network.")
            submitted = st.form_submit_button("E-mail me a code", type="primary")
        if submitted:
            if not agree:
                st.error("Please accept the data note to continue.")
                return
            form = (name, email, mobile, role, pincode, password, confirm)
            try:
                reply = api().register_start(*form)
            except ApiError as error:
                show_problems(error)
                return
            # Only the e-mail and the form stay in this browser session – the server keeps the
            # pending sign-up until the code is verified.
            st.session_state.pending_signup = {**reply, "form": form, "sent_at": time.time()}
            st.rerun()
        return

    st.info(f"We e-mailed a 6-digit code to **{pending['masked_email']}**. "
            f"It expires in {OTP_TTL_SECONDS // 60} minutes. Check your spam folder too.")
    _demo_code(pending)
    wait = int(OTP_RESEND_COOLDOWN - (time.time() - pending["sent_at"]))
    with st.form("otp"):
        code = st.text_input("Enter the code", max_chars=6)
        c1, c2, c3 = st.columns(3)
        verify = c1.form_submit_button("Verify & create account", type="primary")
        # The server enforces the 30-second cooldown; the label just shows how long is left.
        resend = c2.form_submit_button(f"Resend code (wait {wait}s)" if wait > 0 else "Resend code")
        cancel = c3.form_submit_button("Start over")
    if cancel:
        st.session_state.pending_signup = None
        st.rerun()
    if resend:
        try:
            reply = api().register_start(*pending["form"])
        except ApiError as error:          # 30 s cooldown / 5 per hour are enforced by the server too
            show_problems(error)
        else:
            st.session_state.pending_signup = {**reply, "form": pending["form"], "sent_at": time.time()}
            st.rerun()
    if verify:
        try:
            user = api().register_verify(pending["email"], code)
        except ApiError as error:
            show_problems(error)
            return
        st.session_state.pending_signup = None
        sign_in(user)
        st.balloons()
        st.rerun()


def auth_page() -> None:
    hero(APP_NAME, "Every stray deserves a second chance.",
         f"{APP_TAGLINE}. Report an injured animal, rescue, donate or adopt – all in one place.")
    if st.session_state.get("flash"):
        st.warning(st.session_state.pop("flash"))
    numbers = _impact()
    if numbers:
        _impact_row(numbers)
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        sign_in_tab, sign_up_tab = st.tabs(["Sign in", "Create account"])
        with sign_in_tab:
            _login_form()
        with sign_up_tab:
            _signup_form()
        _why_account()
    with right:
        _how_it_works()
        if numbers and numbers.get("spotlight"):
            _spotlight(numbers["spotlight"], numbers["available"])
    _promises()


def _why_account() -> None:
    """Fills the space under the forms: what each kind of account is for."""
    perks = [("🚨", "Citizen", "Report an injured animal in a minute and get an e-mail at every stage of its rescue."),
             ("🚑", "Rescuer", "See SOS calls in your area, most critical first, and keep treatment notes."),
             ("💝", "Donor", "Give by UPI or card, get an 80G receipt, and see exactly where the money went."),
             ("🏡", "Adopter", "Browse recovered animals and apply with a five-question screening.")]
    items = "".join(f'<div class="pc-step"><span class="pc-step-icon">{icon}</span>'
                    f'<div><b>{esc(role)}</b><div class="meta">{esc(text)}</div></div></div>'
                    for icon, role, text in perks)
    st.markdown(f'<div class="pc-card"><h4>Why create an account?</h4><div class="pc-steps-grid">{items}</div>'
                '<div class="meta" style="margin-top:10px">It takes one minute: we e-mail you a 6-digit code to '
                'confirm your address. Your mobile number is optional.</div></div>', unsafe_allow_html=True)


def _impact() -> dict | None:
    """Public numbers for the sign-in page (GET /analytics/impact needs no sign-in)."""
    try:
        return api().impact()
    except ApiError as error:
        show_problems(error)
        return None


def _impact_row(numbers: dict) -> None:
    from ui.styles import kpi
    tiles = [("Animals helped", numbers["helped"], "taken in by a rescuer", "accent"),
             ("In treatment now", numbers["in_treatment"], "on the road or at the clinic", "accent2"),
             ("Recovered", numbers["recovered"], "back on their paws", "success"),
             ("Adopted", numbers["adopted"], "found a family", "accent3"),
             ("Waiting for a home", numbers["available"], "ready to adopt", "accent")]
    for column, (label, value, note, tone) in zip(st.columns(len(tiles)), tiles):
        kpi(column, label, str(value), note, tone=tone)
    st.write("")


def _how_it_works() -> None:
    steps = [("🚨", "Citizens", "send an SOS with a photo and pincode."),
             ("🚑", "Rescuers", "nearby accept it and update treatment."),
             ("💝", "Donors", "fund care and see where every rupee goes."),
             ("🏡", "Adopters", "answer 5 questions to give an animal a home."),
             ("🛡️", "Admins", "allocate funds, review adoptions, keep the audit trail.")]
    items = "".join(f'<div class="pc-step"><span class="pc-step-icon">{icon}</span>'
                    f'<div><b>{esc(who)}</b> <span class="meta">{esc(what)}</span></div></div>'
                    for icon, who, what in steps)
    st.markdown(f'<div class="pc-card"><h4>How PawConnect works</h4><div class="pc-steps-grid">{items}</div></div>',
                unsafe_allow_html=True)


def _spotlight(animals: list[dict], total: int) -> None:
    emoji = {"Dog": "🐕", "Cat": "🐈", "Cow": "🐄", "Bird": "🐦", "Monkey": "🐒"}
    cards = "".join(
        f'<div class="pc-mini-animal"><div class="pc-mini-art">{emoji.get(a["species"], "🐾")}</div>'
        f'<div><b>{esc(a["name"])}</b><div class="meta">{esc(a["breed"])} · {esc(a["gender"])} · '
        f'{float(a["age_years"] or 0):g} yr</div><div class="meta">{esc(a["temperament"])}</div></div></div>'
        for a in animals)
    st.markdown(f'<div class="pc-card"><h4>Waiting for a home <span class="pc-badges">'
                f'{pill(f"{total} ready", "success")}</span></h4><div class="pc-mini-grid">{cards}</div>'
                '<div class="meta" style="margin-top:8px">Sign in as an adopter to apply.</div></div>',
                unsafe_allow_html=True)


def _promises() -> None:
    promises = [("🔍", "Every rupee tracked", "Donations are linked to the animal they treated, and an admin can never "
                                             "allocate more than a fund holds."),
                ("📍", "Help nearby, fast", "SOS calls go to rescuers in the same pincode area, most critical first."),
                ("🔐", "Safe by design", "Passwords are hashed, card numbers are never stored and every action is "
                                        "written to the audit log.")]
    for column, (icon, title, text) in zip(st.columns(3), promises):
        column.markdown(f'<div class="pc-card pc-feature"><div class="pc-feature-icon">{icon}</div>'
                        f'<h4>{esc(title)}</h4><div class="meta">{esc(text)}</div></div>', unsafe_allow_html=True)


# ======================================================================= main
def sidebar(user: User) -> None:
    with st.sidebar:
        st.markdown(f"### 🐾 {APP_NAME}")
        st.markdown(f"**{esc(user.name)}**<br>{pill(user.role)}", unsafe_allow_html=True)
        st.caption(f"{user.email} · {user.pincode}")
        st.divider()
        st.caption("Your permissions")
        st.markdown(" ".join(pill(p.replace("_", " "), "muted") for p in sorted(user.permissions)),
                    unsafe_allow_html=True)
        st.divider()
        theme_toggle()
        if st.button("Sign out"):
            api().logout()
            sign_out()
            st.rerun()
        st.caption(f"Connected: {'in-process (local mode)' if api().mode == 'local' else api().base_url}")


def main() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="🐾", layout="wide")
    _init_state()
    inject_css()
    try:
        user = current_user()
        if user is None:
            auth_page()
            return
        sidebar(user)
        DASHBOARDS[user.role](user)
    except AuthError as error:            # token expired in the middle of a page
        sign_out(error.message)
        st.rerun()
    except ApiError as error:             # API down or another unexpected API problem
        show_problems(error)


main()
