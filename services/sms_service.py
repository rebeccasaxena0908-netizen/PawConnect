"""
SMS notifications – not used for now. PawConnect sends every notification by
e-mail (services/email_service.py).

planned: Twilio/MSG91
"""


def send_sms(mobile: str, text: str) -> dict:
    raise NotImplementedError("SMS is not available yet – PawConnect uses e-mail for all notifications.")
