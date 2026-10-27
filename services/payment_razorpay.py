"""
Real Razorpay payments in TEST mode (Unit 2: REST APIs, JSON, HMAC signatures).

Used only when RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are set (get free test
keys from https://dashboard.razorpay.com → Settings → API Keys, with "Test mode"
switched on). Without them PawConnect keeps using the sandbox simulator in
services/api_service.py, so nothing external is needed by default.

The flow:
  1. create_order()      – our server asks Razorpay for an order (amount in paise).
  2. The donor pays on Razorpay Checkout (their page, their card form – card
     numbers never touch PawConnect).
  3. verify_checkout()   – Checkout gives us order_id, payment_id and a signature:
                           HMAC-SHA256(order_id + "|" + payment_id, key_secret).
  4. verify_webhook()    – Razorpay also POSTs a webhook; its X-Razorpay-Signature
                           header is HMAC-SHA256(raw body, webhook_secret).
We trust a payment only after one of these signatures matches.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from decimal import Decimal


class RazorpayGateway:
    name = "razorpay"

    def __init__(self, key_id: str, key_secret: str, webhook_secret: str = "", client=None):
        self.key_id = key_id
        self._key_secret = key_secret
        self._webhook_secret = webhook_secret
        self._client = client          # tests pass a fake client instead of calling Razorpay

    @classmethod
    def from_env(cls) -> "RazorpayGateway | None":
        key_id, secret = os.environ.get("RAZORPAY_KEY_ID", ""), os.environ.get("RAZORPAY_KEY_SECRET", "")
        if not (key_id and secret):
            return None
        return cls(key_id, secret, os.environ.get("RAZORPAY_WEBHOOK_SECRET", ""))

    @property
    def client(self):
        if self._client is None:
            import razorpay                       # only needed when real keys are configured
            self._client = razorpay.Client(auth=(self.key_id, self._key_secret))
        return self._client

    # ------------------------------------------------------------------ orders
    def create_order(self, amount_rupees: Decimal, receipt: str, notes: dict | None = None) -> dict:
        """POST /v1/orders. Razorpay wants the amount in paise as an integer."""
        paise = int(Decimal(str(amount_rupees)) * 100)
        order = self.client.order.create({"amount": paise, "currency": "INR", "receipt": receipt,
                                          "notes": notes or {}})
        return {"id": order["id"], "amount": order["amount"], "currency": order["currency"],
                "receipt": order.get("receipt", receipt), "status": order.get("status", "created")}

    # ------------------------------------------------------------------ signatures
    @staticmethod
    def _hmac(secret: str, message: bytes) -> str:
        return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()

    def verify_checkout(self, order_id: str, payment_id: str, signature: str) -> bool:
        expected = self._hmac(self._key_secret, f"{order_id}|{payment_id}".encode())
        return hmac.compare_digest(expected, signature or "")

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        if not self._webhook_secret:
            return False                 # never trust a webhook we can't verify
        return hmac.compare_digest(self._hmac(self._webhook_secret, raw_body), signature or "")

    def sign_checkout(self, order_id: str, payment_id: str) -> str:
        """What Razorpay would send – used by the tests."""
        return self._hmac(self._key_secret, f"{order_id}|{payment_id}".encode())


def parse_webhook_event(event: dict) -> tuple[str, str, bool] | None:
    """
    Pull (order_id, payment_id, succeeded) out of a verified webhook JSON body.
    Handles payment.captured, order.paid and payment.failed; other events → None.
    """
    kind = event.get("event", "")
    payment = (event.get("payload", {}).get("payment", {}) or {}).get("entity", {}) or {}
    if kind in ("payment.captured", "order.paid"):
        return payment.get("order_id", ""), payment.get("id", ""), True
    if kind == "payment.failed":
        return payment.get("order_id", ""), payment.get("id", ""), False
    return None
