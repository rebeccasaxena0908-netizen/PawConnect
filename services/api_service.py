"""
External APIs and JSON (Unit 2: `requests`, `json`, `urllib`).

1. Geocoding – turns a pincode into district, state and map coordinates using
   the free India Post API and OpenStreetMap Nominatim. Works offline too: if
   there's no internet it falls back to the postal-zone table below.
2. Payment gateway simulator – behaves like Razorpay/Stripe test mode: creates
   an order, returns a JSON webhook payload signed with HMAC-SHA256, and the app
   verifies the signature before trusting it. No real money ever moves.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import random
import secrets
import time
from urllib.parse import urlencode

import requests

from config import (GEOCODE_TIMEOUT, INDIA_POST_API, NOMINATIM_API, PAYMENT_SECRET,
                    USER_AGENT)

# First two pincode digits → (region, latitude, longitude) of a central city.
# Indian pincodes are allocated by zone, so this gives a sensible offline location.
PINCODE_ZONES: dict[str, tuple[str, float, float]] = {
    "11": ("Delhi", 28.6139, 77.2090),
    "12": ("Haryana", 28.4595, 77.0266), "13": ("Haryana", 30.3782, 76.7767),
    "14": ("Punjab", 30.9010, 75.8573), "15": ("Punjab", 31.6340, 74.8723),
    "16": ("Chandigarh / Punjab", 30.7333, 76.7794),
    "17": ("Himachal Pradesh", 31.1048, 77.1734),
    "18": ("Jammu & Kashmir", 32.7266, 74.8570), "19": ("Jammu & Kashmir", 34.0837, 74.7973),
    "20": ("Uttar Pradesh (West)", 28.6692, 77.4538), "21": ("Uttar Pradesh", 25.4358, 81.8463),
    "22": ("Uttar Pradesh (Central)", 26.8467, 80.9462), "23": ("Uttar Pradesh", 25.3176, 82.9739),
    "24": ("Uttarakhand / UP", 30.3165, 78.0322), "25": ("Uttar Pradesh", 27.1767, 78.0081),
    "26": ("Uttarakhand", 29.2183, 79.5130), "27": ("Uttar Pradesh (East)", 26.7606, 83.3732),
    "28": ("Uttar Pradesh", 27.8974, 78.0880),
    "30": ("Rajasthan", 26.9124, 75.7873), "31": ("Rajasthan", 26.4499, 74.6399),
    "32": ("Rajasthan", 25.2138, 75.8648), "33": ("Rajasthan", 28.0229, 73.3119),
    "34": ("Rajasthan", 26.2389, 73.0243),
    "36": ("Gujarat", 22.3039, 70.8022), "37": ("Gujarat", 23.2420, 69.6669),
    "38": ("Gujarat", 23.0225, 72.5714), "39": ("Gujarat", 21.1702, 72.8311),
    "40": ("Maharashtra (Mumbai)", 19.0760, 72.8777), "41": ("Maharashtra (Pune)", 18.5204, 73.8567),
    "42": ("Maharashtra (Nashik)", 19.9975, 73.7898), "43": ("Maharashtra", 19.8762, 75.3433),
    "44": ("Maharashtra (Nagpur)", 21.1458, 79.0882),
    "45": ("Madhya Pradesh", 22.7196, 75.8577), "46": ("Madhya Pradesh", 23.2599, 77.4126),
    "47": ("Madhya Pradesh", 26.2183, 78.1828), "48": ("Madhya Pradesh", 23.1815, 79.9864),
    "49": ("Chhattisgarh", 21.2514, 81.6296),
    "50": ("Telangana", 17.3850, 78.4867),
    "51": ("Andhra Pradesh", 14.4426, 79.9865), "52": ("Andhra Pradesh", 16.5062, 80.6480),
    "53": ("Andhra Pradesh", 17.6868, 83.2185),
    "56": ("Karnataka (Bengaluru)", 12.9716, 77.5946), "57": ("Karnataka", 12.2958, 76.6394),
    "58": ("Karnataka", 15.3647, 75.1240), "59": ("Karnataka", 15.8497, 74.4977),
    "60": ("Tamil Nadu (Chennai)", 13.0827, 80.2707), "61": ("Tamil Nadu", 10.7905, 78.7047),
    "62": ("Tamil Nadu", 9.9252, 78.1198), "63": ("Tamil Nadu", 11.6643, 78.1460),
    "64": ("Tamil Nadu", 11.0168, 76.9558),
    "67": ("Kerala", 11.2588, 75.7804), "68": ("Kerala", 9.9312, 76.2673),
    "69": ("Kerala", 8.5241, 76.9366),
    "70": ("West Bengal (Kolkata)", 22.5726, 88.3639), "71": ("West Bengal", 22.5958, 88.2636),
    "72": ("West Bengal", 22.4200, 87.3200), "73": ("West Bengal", 26.7271, 88.3953),
    "74": ("West Bengal", 23.2324, 87.8615),
    "75": ("Odisha", 20.2961, 85.8245), "76": ("Odisha", 19.3150, 84.7941),
    "77": ("Odisha", 21.4669, 83.9812),
    "78": ("Assam", 26.1445, 91.7362), "79": ("North East", 25.5788, 91.8933),
    "80": ("Bihar", 25.5941, 85.1376), "81": ("Bihar", 25.2425, 86.9842),
    "82": ("Bihar / Jharkhand", 24.7914, 85.0002), "83": ("Jharkhand", 23.3441, 85.3096),
    "84": ("Bihar", 26.1209, 85.3647), "85": ("Bihar", 25.8560, 87.4689),
}


def offline_location(pincode: str) -> dict:
    region, lat, lon = PINCODE_ZONES.get(str(pincode)[:2], ("India", 22.9734, 78.6569))
    # Spread nearby pincodes a little so they don't sit on exactly the same point.
    rnd = random.Random(int(pincode) if str(pincode).isdigit() else 0)
    return {"latitude": round(lat + rnd.uniform(-0.08, 0.08), 5),
            "longitude": round(lon + rnd.uniform(-0.08, 0.08), 5),
            "district": "", "state": region, "post_office": "", "source": "offline zone table"}


def lookup_pincode(pincode: str, timeout: float = GEOCODE_TIMEOUT) -> dict | None:
    """India Post API → district, state and post office name, or None."""
    try:
        response = requests.get(INDIA_POST_API.format(pincode=pincode), timeout=timeout,
                                headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        payload = json.loads(response.text)          # the API returns a JSON list
        first = payload[0] if isinstance(payload, list) and payload else {}
        offices = first.get("PostOffice") or []
        if first.get("Status") != "Success" or not offices:
            return None
        office = offices[0]
        return {"district": office.get("District", ""), "state": office.get("State", ""),
                "post_office": office.get("Name", "")}
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def nominatim_coordinates(pincode: str, timeout: float = GEOCODE_TIMEOUT) -> tuple[float, float] | None:
    """OpenStreetMap Nominatim: pincode → (lat, lon). Query string built with urllib."""
    url = f"{NOMINATIM_API}?{urlencode({'postalcode': pincode, 'country': 'India', 'format': 'json', 'limit': 1})}"
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        results = response.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except (requests.RequestException, ValueError, KeyError, IndexError):
        pass
    return None


def geocode_pincode(pincode: str, use_network: bool = True) -> dict:
    """Best available location for a pincode. Never raises – falls back to offline data."""
    location = offline_location(pincode)
    if not use_network:
        return location
    details = lookup_pincode(pincode)
    coords = nominatim_coordinates(pincode)
    if details:
        location.update({k: v for k, v in details.items() if v})
        location["source"] = "India Post API"
    if coords:
        location["latitude"], location["longitude"] = round(coords[0], 5), round(coords[1], 5)
        location["source"] = "India Post + OpenStreetMap" if details else "OpenStreetMap"
    return location


# ======================================================================= payments
class PaymentGatewaySimulator:
    """
    A tiny stand-in for a real payment gateway's test mode.

    create_order() → dict          (like POST /orders)
    capture()      → (json, sig)   (the webhook body + its X-Signature header)
    verify_signature(), parse_webhook() – what the server does on receipt.
    """

    def __init__(self, secret: str = PAYMENT_SECRET, declined_accounts: set[str] | None = None):
        self._secret = secret.encode()
        self.declined_accounts = declined_accounts or set()

    def create_order(self, amount_rupees: float, receipt: str, currency: str = "INR") -> dict:
        if amount_rupees <= 0:
            raise ValueError("Amount must be positive.")
        return {
            "id": f"order_{secrets.token_hex(7)}",
            "amount": int(round(amount_rupees * 100)),   # gateways work in paise
            "currency": currency,
            "receipt": receipt,
            "status": "created",
            "created_at": int(time.time()),
        }

    def sign(self, payload: str) -> str:
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()

    def capture(self, order: dict, method: str, account_key: str, masked_account: str) -> tuple[str, str]:
        """Pretend the donor paid. Returns the webhook JSON text and its signature."""
        declined = account_key in self.declined_accounts
        event = {
            "event": "payment.failed" if declined else "payment.captured",
            "created_at": int(time.time()),
            "payload": {
                "payment": {
                    "id": f"pay_{secrets.token_hex(7)}",
                    "order_id": order["id"],
                    "amount": order["amount"],
                    "currency": order["currency"],
                    "method": method.lower(),
                    "account": masked_account,
                    "status": "failed" if declined else "captured",
                    "error_description": "Payment declined by bank (sandbox)" if declined else None,
                }
            },
        }
        body = json.dumps(event, separators=(",", ":"))
        return body, self.sign(body)

    def verify_signature(self, body: str, signature: str) -> bool:
        return hmac.compare_digest(self.sign(body), signature or "")

    @staticmethod
    def parse_webhook(body: str) -> dict:
        """Pull the fields the app needs out of the JSON payload."""
        payment = json.loads(body)["payload"]["payment"]
        return {"payment_id": payment["id"], "order_id": payment["order_id"],
                "amount": payment["amount"] / 100, "status": payment["status"],
                "error": payment.get("error_description")}
