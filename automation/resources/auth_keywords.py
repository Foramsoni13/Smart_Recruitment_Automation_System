"""
Auth Keywords Helper for Robot Framework
Provides automated TOTP 2FA code generation using pyotp.
"""

import pyotp

def generate_totp_token(secret_key: str) -> str:
    """Generates a valid 6-digit TOTP token from a base32 secret seed."""
    totp = pyotp.TOTP(secret_key)
    return totp.now()

def verify_totp_token(secret_key: str, token: str) -> bool:
    """Verifies if the given token is valid for the secret key."""
    totp = pyotp.TOTP(secret_key)
    return totp.verify(token)
