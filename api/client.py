"""
PawConnectClient – the one way the web app and the desktop console talk to PawConnect.

    client = PawConnectClient()                  # mode from PAWCONNECT_MODE (api / local / auto)
    client.login("admin@pawconnect.org", "Admin@123")
    cases = client.cases()                       # pandas DataFrame, same columns as the table
    client.accept_case("RC-0046")

* "api" mode   – real HTTP with requests.Session to PAWCONNECT_API_URL. The JWT
                 is stored on the session and sent as  Authorization: Bearer ...
* "local" mode – the same Flask app runs inside this process through Flask's
                 test client: no server, no network – handy for offline demos.
* "auto"       – use the API if /health answers, otherwise local.

Every failure becomes an ApiError subclass with .status, .message and .problems,
so the UIs only need  `except ApiError as error: show_problems(error)`.
"""
from __future__ import annotations

import io
from functools import lru_cache

import pandas as pd
import requests

import config
from config import SCHEMAS


# ======================================================================= errors
class ApiError(Exception):
    def __init__(self, status: int, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.status, self.message = status, message
        self.problems = list(details or []) or [message]


class AuthError(ApiError):          # 401 – not signed in / token expired
    pass


class Forbidden(ApiError):          # 403
    pass


class NotFoundError(ApiError):      # 404
    pass


class ConflictError(ApiError):      # 409
    pass


class InvalidInput(ApiError):       # 400 / 422
    pass


class PaymentFailed(ApiError):      # 402
    pass


class TooManyRequests(ApiError):    # 429
    pass


class ServerUnavailable(ApiError):  # can't reach the server / 5xx
    pass


ERRORS = {400: InvalidInput, 401: AuthError, 402: PaymentFailed, 403: Forbidden, 404: NotFoundError,
          409: ConflictError, 413: InvalidInput, 422: InvalidInput, 429: TooManyRequests,
          502: ServerUnavailable, 503: ServerUnavailable}


# ======================================================================= transports
class _Reply:
    """The few response fields we need, whichever transport produced them."""

    def __init__(self, status: int, content: bytes, content_type: str):
        self.status, self.content, self.content_type = status, content, content_type

    def json(self):
        import json
        return json.loads(self.content or b"null")


class HttpTransport:
    def __init__(self, base_url: str, timeout: float):
        self.base_url, self.timeout = base_url.rstrip("/"), timeout
        self.session = requests.Session()

    def send(self, method, path, headers, json=None, params=None, files=None) -> _Reply:
        upload = {k: (name, data) for k, (name, data) in (files or {}).items()} or None
        try:
            r = self.session.request(method, self.base_url + path, headers=headers, json=json,
                                     params=params, files=upload, timeout=self.timeout)
        except requests.Timeout:
            raise ServerUnavailable(504, f"The API at {self.base_url} took too long to answer.") from None
        except requests.ConnectionError:
            raise ServerUnavailable(503, f"Can't reach the PawConnect API at {self.base_url}.",
                                    ["Start it with:  python main.py --api",
                                     "or run everything offline with PAWCONNECT_MODE=local"]) from None
        return _Reply(r.status_code, r.content, r.headers.get("Content-Type", ""))


@lru_cache(maxsize=1)
def _local_app():
    """One in-process Flask app per Python process (local mode)."""
    from api import create_app
    return create_app()


class LocalTransport:
    def __init__(self):
        self.client = _local_app().test_client()

    def send(self, method, path, headers, json=None, params=None, files=None) -> _Reply:
        kwargs = {"headers": headers, "query_string": params}
        if files:
            kwargs["data"] = {k: (io.BytesIO(data), name) for k, (name, data) in files.items()}
            kwargs["content_type"] = "multipart/form-data"
        elif json is not None:
            kwargs["json"] = json
        r = self.client.open(path, method=method, **kwargs)
        return _Reply(r.status_code, r.data, r.headers.get("Content-Type", ""))


def api_is_up(base_url: str = config.API_URL, timeout: float = 1.5) -> bool:
    try:
        return requests.get(base_url.rstrip("/") + "/health", timeout=timeout).ok
    except requests.RequestException:
        return False


def resolve_mode(mode: str | None = None, base_url: str = config.API_URL) -> str:
    mode = (mode or config.UI_MODE).lower()
    if mode == "auto":
        return "api" if api_is_up(base_url) else "local"
    if mode not in ("api", "local"):
        raise ValueError("PAWCONNECT_MODE must be api, local or auto.")
    return mode


# ======================================================================= the client
class PawConnectClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, mode: str | None = None,
                 timeout: float = config.API_TIMEOUT):
        self.base_url = base_url or config.API_URL
        self.mode = resolve_mode(mode, self.base_url)
        self.transport = LocalTransport() if self.mode == "local" else HttpTransport(self.base_url, timeout)
        self.token = token
        self.user: dict | None = None

    def __repr__(self) -> str:
        where = "in-process" if self.mode == "local" else self.base_url
        return f"PawConnectClient({where}, signed_in={self.token is not None})"

    # ------------------------------------------------------------------ plumbing
    def _call(self, method: str, path: str, json=None, params=None, files=None, raw: bool = False):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        reply = self.transport.send(method, path, headers, json=json, params=params, files=files)
        if reply.status >= 400:
            try:
                body = reply.json() or {}
            except ValueError:
                body = {}
            message = body.get("error") or f"Request failed ({reply.status})."
            error_class = ERRORS.get(reply.status, ServerUnavailable if reply.status >= 500 else ApiError)
            if reply.status == 401:
                self.token = None           # make the UI show the sign-in screen again
            raise error_class(reply.status, message, body.get("details"))
        return reply.content if raw else reply.json()

    @staticmethod
    def _frame(rows: list[dict], name: str) -> pd.DataFrame:
        """JSON rows → DataFrame of text, exactly like data_handler.load_table() returns."""
        columns = [c for c in SCHEMAS[name] if not (name == "users" and c == "password_hash")]
        extras = [k for k in (rows[0] if rows else {}) if k not in columns]   # e.g. rescuer_name
        df = pd.DataFrame(rows, columns=columns + extras)
        return df.fillna("").astype(str) if not df.empty else df

    # ------------------------------------------------------------------ auth
    def login(self, identifier: str, password: str) -> dict:
        reply = self._call("POST", "/auth/login", json={"identifier": identifier, "password": password})
        self.token, self.user = reply["access_token"], reply["user"]
        return self.user

    def logout(self) -> None:
        if self.token:
            try:
                self._call("POST", "/auth/logout")
            except ApiError:
                pass
        self.token, self.user = None, None

    def me(self) -> dict:
        self.user = self._call("GET", "/me")
        return self.user

    def register_start(self, name, email, mobile, role, pincode, password, confirm=None) -> dict:
        """Step 1 of sign-up: the server e-mails a code. mobile may be ""."""
        return self._call("POST", "/auth/register/start", json={
            "name": name, "email": email, "mobile": mobile or "", "role": role, "pincode": pincode,
            "password": password, "confirm": confirm})

    def register_verify(self, email: str, otp: str) -> dict:
        reply = self._call("POST", "/auth/register/verify", json={"email": email, "otp": otp})
        self.token, self.user = reply["access_token"], reply["user"]
        return self.user

    def forgot_password(self, email: str) -> dict:
        return self._call("POST", "/auth/password/forgot", json={"email": email})

    def reset_password(self, email: str, otp: str, new_password: str, confirm: str | None = None) -> dict:
        return self._call("POST", "/auth/password/reset", json={
            "email": email, "otp": otp, "new_password": new_password, "confirm": confirm})

    def health(self) -> dict:
        return self._call("GET", "/health")

    def impact(self) -> dict:
        return self._call("GET", "/analytics/impact")

    # ------------------------------------------------------------------ cases
    def cases(self) -> pd.DataFrame:
        return self._frame(self._call("GET", "/cases"), "rescue_cases")

    def case(self, case_id: str) -> dict:
        return self._call("GET", f"/cases/{case_id}")

    def create_case(self, animal_type, injury_level, description, pincode, address="",
                    use_network=True, photo_bytes: bytes | None = None, photo_name: str = "") -> dict:
        case = self._call("POST", "/cases", json={
            "animal_type": animal_type, "injury_level": injury_level, "description": description,
            "pincode": pincode, "address": address, "use_network": use_network})
        if photo_bytes:
            case = self.upload_photo(case["case_id"], photo_bytes, photo_name)
        return case

    def accept_case(self, case_id: str) -> dict:
        return self._call("POST", f"/cases/{case_id}/accept")

    def advance_case(self, case_id: str, note: str = "") -> dict:
        return self._call("POST", f"/cases/{case_id}/advance", json={"note": note})

    def add_note(self, case_id: str, note: str = "", estimated_cost: float | None = None) -> dict:
        return self._call("POST", f"/cases/{case_id}/notes", json={"note": note, "estimated_cost": estimated_cost})

    def upload_photo(self, case_id: str, data: bytes, filename: str) -> dict:
        return self._call("POST", f"/cases/{case_id}/photo", files={"photo": (filename, data)})

    def photo(self, case_id: str) -> bytes | None:
        try:
            return self._call("GET", f"/cases/{case_id}/photo", raw=True)
        except NotFoundError:
            return None

    def assign_case(self, case_id: str, rescuer_id: str) -> dict:
        return self._call("POST", f"/cases/{case_id}/assign", json={"rescuer_id": rescuer_id})

    def set_case_status(self, case_id: str, status: str) -> dict:
        return self._call("POST", f"/cases/{case_id}/status", json={"status": status})

    def import_cases(self, data: bytes, filename: str = "offline.csv") -> dict:
        return self._call("POST", "/cases/import", files={"file": (filename, data)})

    # ------------------------------------------------------------------ money
    def donate(self, amount, contribution_type: str, method: str, details: dict | None = None,
               case_id: str = "") -> dict:
        """Returns {"donation": {...}, "receipt": "...", "checkout": {...} (Razorpay only)}."""
        return self._call("POST", "/donations", json={
            "amount": str(amount), "contribution_type": contribution_type, "method": method,
            "case_id": case_id or "", **(details or {})})

    def donations(self) -> pd.DataFrame:
        return self._frame(self._call("GET", "/donations"), "donations")

    def donation(self, transaction_id: str) -> dict:
        return self._call("GET", f"/donations/{transaction_id}")

    def receipt(self, transaction_id: str) -> str:
        return self._call("GET", f"/donations/{transaction_id}/receipt")["receipt"]

    def payment_config(self) -> dict:
        return self._call("GET", "/payments/config")

    def funds_overview(self) -> pd.DataFrame:
        """Same shape as pandas_engine.funds_overview(): index = fund name."""
        df = pd.DataFrame(self._call("GET", "/funds/overview"))
        return df.set_index("fund") if not df.empty else df

    def allocate(self, case_id: str, amount, purpose: str, source_fund: str, notes: str = "") -> dict:
        return self._call("POST", "/funds/allocate", json={
            "case_id": case_id, "amount": str(amount), "purpose": purpose, "source_fund": source_fund,
            "notes": notes})

    def allocations(self) -> pd.DataFrame:
        return self._frame(self._call("GET", "/funds/allocations"), "allocations")

    def case_funding(self) -> pd.DataFrame:
        df = pd.DataFrame(self._call("GET", "/funds/case-funding"))
        if not df.empty:
            df["reported_at"] = pd.to_datetime(df["reported_at"])
        return df

    # ------------------------------------------------------------------ adoption
    def animals(self, available_only: bool = False) -> pd.DataFrame:
        rows = self._call("GET", "/animals", params={"available": str(available_only).lower()})
        return self._frame(rows, "animals")

    def add_animal(self, name, species, breed, age_years, gender, vaccinated, sterilized, temperament,
                   description, case_id="") -> dict:
        return self._call("POST", "/animals", json={
            "name": name, "species": species, "breed": breed, "age_years": float(age_years),
            "gender": gender, "vaccinated": bool(vaccinated), "sterilized": bool(sterilized),
            "temperament": temperament, "description": description, "case_id": case_id or ""})

    def apply_adoption(self, animal_id: str, answers: dict, reason: str = "") -> dict:
        return self._call("POST", "/adoption/applications",
                          json={"animal_id": animal_id, "answers": answers, "reason": reason})

    def applications(self) -> pd.DataFrame:
        return self._frame(self._call("GET", "/adoption/applications"), "adoption_applications")

    def review_application(self, application_id: str, decision: str) -> dict:
        return self._call("POST", f"/adoption/applications/{application_id}/review", json={"decision": decision})

    # ------------------------------------------------------------------ inventory & users
    def inventory(self) -> pd.DataFrame:
        return self._frame(self._call("GET", "/inventory"), "inventory")

    def save_inventory(self, df: pd.DataFrame) -> int:
        items = df.drop(columns=["updated_at"], errors="ignore").fillna("").astype(str).to_dict(orient="records")
        return self._call("PUT", "/inventory", json={"items": items})["saved"]

    def users(self, role: str | None = None) -> pd.DataFrame:
        return self._frame(self._call("GET", "/users", params={"role": role} if role else None), "users")

    def rescuers(self) -> dict[str, str]:
        return self._call("GET", "/users/rescuers")

    # ------------------------------------------------------------------ analytics & admin
    def summary(self) -> dict:
        """Dashboard numbers. Monthly lists come back as pandas Series ready for the charts."""
        data = self._call("GET", "/analytics/summary")
        for key in ("monthly_donations", "monthly_expenditure"):
            points = data[key]
            data[key] = pd.Series([p["amount"] for p in points], index=pd.to_datetime([p["month"] for p in points]),
                                  dtype=float)
        data["utilization"] = pd.Series(data["utilization"], dtype=float)
        data["cases_by_status"] = pd.Series(data["cases_by_status"], dtype=int)
        data["by_fund"] = pd.DataFrame(data["by_fund"]).set_index("contribution_type")
        return data

    def audit_log(self) -> pd.DataFrame:
        return pd.DataFrame(self._call("GET", "/admin/audit"),
                            columns=["id", "timestamp", "actor", "role", "action", "details"])

    def audit_log_xml(self) -> bytes:
        return self._call("GET", "/admin/audit.xml", raw=True)

    def table(self, name: str) -> pd.DataFrame:
        return self._frame(self._call("GET", f"/admin/tables/{name}"), name)

    def export(self, name: str, kind: str = "csv") -> bytes:
        return self._call("GET", f"/admin/export/{name}", params={"format": kind}, raw=True)

    def backup(self) -> dict:
        return self._call("POST", "/admin/backup")

    def email_status(self) -> dict:
        return self._call("GET", "/admin/email")

    def send_test_email(self, to: str) -> dict:
        return self._call("POST", "/admin/email/test", json={"to": to})
