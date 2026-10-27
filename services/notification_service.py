"""
One-time passwords and receipt text.

* OTPManager – creates and checks 6-digit codes. Only a hash of each code is
  kept; codes expire after 5 minutes, allow 3 tries and work once. Sending is
  limited: one code per 30 seconds and at most 5 per address per hour.
* build_receipt / format_inr – the plain-text donation receipt.

The codes and receipts are delivered by e-mail – see services/email_service.py.
(SMS is not used for now – see services/sms_service.py.)
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time

from config import (OTP_LENGTH, OTP_MAX_ATTEMPTS, OTP_MAX_PER_HOUR, OTP_RESEND_COOLDOWN,
                    OTP_TTL_SECONDS, ORG_80G_NO, ORG_NAME)


class OTPLimitError(Exception):
    """Asked for a new code too soon or too often."""


class OTPManager:
    """Creates and checks one-time passwords. Only a hash of each code is kept."""

    def __init__(self, ttl: int = OTP_TTL_SECONDS, max_attempts: int = OTP_MAX_ATTEMPTS,
                 length: int = OTP_LENGTH, cooldown: int = OTP_RESEND_COOLDOWN,
                 max_per_hour: int = OTP_MAX_PER_HOUR):
        self.ttl = ttl
        self.max_attempts = max_attempts
        self.length = length
        self.cooldown = cooldown
        self.max_per_hour = max_per_hour
        self._codes: dict[str, dict] = {}
        self._sent: dict[str, list[float]] = {}        # address → times a code was sent
        self._lock = threading.Lock()

    @staticmethod
    def _hash(code: str) -> str:
        return hashlib.sha256(code.encode()).hexdigest()

    def wait_seconds(self, address: str) -> tuple[int, str]:
        """(0, "") if a new code may be sent to this address now, else (seconds, reason)."""
        now = time.time()
        recent = [t for t in self._sent.get(address, []) if now - t < 3600]
        self._sent[address] = recent
        if recent and now - recent[-1] < self.cooldown:
            wait = int(self.cooldown - (now - recent[-1])) + 1
            return wait, f"Please wait {wait} seconds before asking for a new code."
        if len(recent) >= self.max_per_hour:
            wait = int(3600 - (now - recent[0])) + 1
            return wait, f"Too many codes for this address. Try again in {wait // 60 + 1} minutes."
        return 0, ""

    def generate(self, key: str, address: str | None = None) -> str:
        """
        New code for `key` (e.g. "signup:riya@example.com"). The sending limits are
        counted per `address` (the e-mail), so sign-up and password reset share them.
        Raises OTPLimitError when the cooldown or hourly limit is hit.
        """
        address = address or key
        with self._lock:
            wait, reason = self.wait_seconds(address)
            if wait:
                raise OTPLimitError(reason)
            code = "".join(secrets.choice("0123456789") for _ in range(self.length))
            self._codes[key] = {"hash": self._hash(code), "expires": time.time() + self.ttl, "attempts": 0}
            self._sent.setdefault(address, []).append(time.time())
        return code

    def discard(self, key: str) -> None:
        """Forget a code (e.g. when the e-mail with it could not be sent)."""
        with self._lock:
            self._codes.pop(key, None)

    def seconds_left(self, key: str) -> int:
        entry = self._codes.get(key)
        return max(0, int(entry["expires"] - time.time())) if entry else 0

    def verify(self, key: str, code: str) -> tuple[bool, str]:
        with self._lock:
            entry = self._codes.get(key)
            if entry is None:
                return False, "No OTP was sent. Please request a new one."
            if time.time() > entry["expires"]:
                self._codes.pop(key, None)
                return False, "The OTP has expired. Please request a new one."
            if entry["attempts"] >= self.max_attempts:
                self._codes.pop(key, None)
                return False, "Too many wrong attempts. Please request a new OTP."
            entry["attempts"] += 1
            if hmac.compare_digest(entry["hash"], self._hash((code or "").strip())):
                self._codes.pop(key, None)              # single use
                return True, "Verified."
            left = self.max_attempts - entry["attempts"]
            return False, f"Wrong OTP. {left} attempt{'s' if left != 1 else ''} left."


def format_inr(amount: float) -> str:
    """Indian digit grouping: 1234567.5 → ₹12,34,567.50"""
    amount = float(amount)
    rupees, paise = f"{abs(amount):.2f}".split(".")
    if len(rupees) > 3:
        head, tail = rupees[:-3], rupees[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        rupees = ",".join(groups + [tail])
    return f"{'-' if amount < 0 else ''}₹{rupees}.{paise}"


def build_receipt(donation: dict) -> str:
    """Plain-text donation receipt (shown on screen, downloadable, and the text part of the e-mail)."""
    lines = [
        f"{ORG_NAME}",
        "DONATION RECEIPT",
        "=" * 44,
        f"Receipt / Transaction ID : {donation['transaction_id']}",
        f"Date                     : {donation['timestamp']}",
        f"Donor                    : {donation['donor_name']}",
        f"E-mail                   : {donation.get('donor_email') or '-'}",
        f"Amount                   : {format_inr(donation['amount'])}",
        f"Fund                     : {donation['contribution_type']}",
    ]
    if donation.get("case_id"):
        lines.append(f"Rescue case              : {donation['case_id']}")
    sandbox = donation.get("method") in ("UPI", "Card")
    lines += [
        f"Paid by                  : {donation['method']} ({donation['masked_account']})",
        f"Gateway reference        : {donation['payment_ref']}",
        f"Status                   : {donation['status']}",
        "=" * 44,
        f"80G registration: {ORG_80G_NO}",
        "Donations may be eligible for deduction under Section 80G",
        "of the Income Tax Act.",
        ("Sandbox payment – this is a student project and no real" if sandbox
         else "Razorpay TEST mode payment – no real money was"),
        ("money was charged." if sandbox else "charged."),
        "",
        "Thank you for helping a stray animal heal.",
    ]
    return "\n".join(lines)
