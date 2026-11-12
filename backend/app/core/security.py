import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote


# Scrypt parameters: secure work factor that executes cleanly on Python 3.11+ without C extensions
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def hash_secret(plain: str) -> str:
    """Hash a password, PIN, or recovery code using scrypt with a 16-byte cryptographic salt."""
    if not plain:
        raise ValueError("Secret cannot be empty")
    salt = os.urandom(16)
    dk = hashlib.scrypt(plain.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_secret(plain: str, stored_hash: str) -> bool:
    """Constant-time verification of a scrypt-hashed secret."""
    try:
        alg, n_s, r_s, p_s, salt_b64, dk_b64 = stored_hash.split("$")
        if alg != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        actual = hashlib.scrypt(
            plain.encode("utf-8"),
            salt=salt,
            n=int(n_s),
            r=int(r_s),
            p=int(p_s),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def generate_session_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hex_digest). Only the digest is persisted in the DB."""
    raw = secrets.token_urlsafe(48)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, digest


def hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# --- Pure-Python RFC 6238 TOTP MFA ---

def generate_totp_secret() -> str:
    """Generate a base32-encoded 160-bit TOTP secret."""
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def _totp_at(secret_b32: str, counter: int, digits: int = 6) -> str:
    padded = secret_b32.upper() + "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(code_int).zfill(digits)


def current_totp(secret_b32: str, for_time: int | None = None, step: int = 30) -> str:
    ts = int(for_time if for_time is not None else time.time())
    return _totp_at(secret_b32, ts // step)


def verify_totp(secret_b32: str, code: str, for_time: int | None = None, step: int = 30, window: int = 1) -> bool:
    if not code or not code.isdigit():
        return False
    ts = int(for_time if for_time is not None else time.time())
    counter = ts // step
    for offset in range(-window, window + 1):
        expected = _totp_at(secret_b32, counter + offset)
        if hmac.compare_digest(code, expected):
            return True
    return False


def totp_provisioning_uri(secret_b32: str, account_email: str, issuer: str = "BOSS") -> str:
    label = quote(f"{issuer}:{account_email}")
    return f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"


def generate_recovery_codes(count: int = 6) -> tuple[list[str], list[str]]:
    """Return (plain_codes_for_owner_once, hashed_codes_for_db)."""
    plain = [f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}" for _ in range(count)]
    hashed = [hash_secret(c) for c in plain]
    return plain, hashed


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def session_expiry(hours: int) -> datetime:
    return utcnow() + timedelta(hours=hours)

