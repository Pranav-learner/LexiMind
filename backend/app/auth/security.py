"""Password hashing and signed auth tokens — stdlib only.

WHY no external crypto libs:
- The project is offline-first and we want to keep the dependency tree minimal. Python's
  standard library already ships everything a *minimal* auth system needs:
    * `hashlib.pbkdf2_hmac` for salted, iterated password hashing (industry-standard KDF),
    * `hmac` + `hashlib.sha256` for tamper-proof, stateless session tokens.
- This is deliberately a *minimal* token scheme (a compact signed JWT-alike), not a full
  OAuth/JWT stack. It is sufficient for single-owner scoping today and can be swapped for
  `python-jose`/`pyjwt` later without touching call sites (only this module changes).

Token format:  base64url(payload_json) + "." + base64url(hmac_sha256(payload))
Payload:        {"sub": <user_id>, "exp": <unix_seconds>}
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional, Tuple

from app.core.config import settings

_ALGO = "pbkdf2_sha256"


# --------------------------------------------------------------------------- passwords
def hash_password(password: str, *, iterations: Optional[int] = None) -> str:
    """Return a self-describing password hash: `pbkdf2_sha256$iters$salt$hash`."""
    iterations = iterations or settings.pbkdf2_iterations
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_ALGO}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time verification of a password against a stored hash."""
    try:
        algo, iters, salt_hex, hash_hex = encoded.split("$")
        if algo != _ALGO:
            return False
        expected = bytes.fromhex(hash_hex)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(candidate, expected)


# ------------------------------------------------------------------------------ tokens
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(payload_b64: str) -> str:
    sig = hmac.new(settings.secret_key.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
    return _b64e(sig.digest())


def create_token(user_id: str, *, ttl_seconds: Optional[int] = None, now: Optional[int] = None) -> str:
    """Issue a signed token carrying the user id and an expiry."""
    ttl = ttl_seconds if ttl_seconds is not None else settings.token_ttl_seconds
    issued = int(now if now is not None else time.time())
    payload = {"sub": user_id, "exp": issued + ttl}
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_sign(payload_b64)}"


def decode_token(token: str, *, now: Optional[int] = None) -> Optional[str]:
    """Return the user id if the token is authentic and unexpired, else None."""
    parsed = _verify_and_load(token, now=now)
    return parsed[0] if parsed else None


def _verify_and_load(token: str, *, now: Optional[int] = None) -> Optional[Tuple[str, dict]]:
    try:
        payload_b64, sig = token.split(".")
    except (ValueError, AttributeError):
        return None
    if not hmac.compare_digest(sig, _sign(payload_b64)):
        return None  # bad signature — tampered or wrong secret
    try:
        payload = json.loads(_b64d(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return None
    current = int(now if now is not None else time.time())
    if int(payload.get("exp", 0)) < current:
        return None  # expired
    sub = payload.get("sub")
    return (sub, payload) if sub else None
