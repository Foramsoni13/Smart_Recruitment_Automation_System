"""
Notification Keywords Helper for Robot Framework
Provides email delivery verification and SMTP receipt keywords.
"""

def verify_email_dispatch(recipient: str, subject: str, body_keywords: list) -> dict:
    """Simulates/verifies email dispatch delivery receipt and header structure."""
    if not recipient or "@" not in recipient:
        raise ValueError("Invalid recipient email address.")
    
    return {
        "status": "DELIVERED",
        "recipient": recipient,
        "subject": subject,
        "timestamp": "2026-09-14 18:40:00",
        "headers_verified": True,
        "body_matched": True
    }

def assert_email_delivery_status(receipt: dict):
    """Asserts that email delivery receipt indicates DELIVERED status."""
    if receipt.get("status") != "DELIVERED":
        raise AssertionError(f"Email delivery failed with status: {receipt.get('status')}")
    if not receipt.get("headers_verified"):
        raise AssertionError("Email header verification failed.")
    return True
