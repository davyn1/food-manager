"""Password hashing with the standard library's scrypt. Pure, no I/O.

Stored format: "scrypt$<n>$<r>$<p>$<salt base64>$<hash base64>", so the cost can be
raised later without breaking existing passwords.
"""

import base64
import hashlib
import hmac
import secrets

# scrypt cost. n=2**15, r=8 uses about 32 MB and ~0.1 s per hash: slow for attackers,
# fine for a login. Tests lower it (see tests/conftest.py).
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
        maxmem=128 * n * r * 2, dklen=_KEY_BYTES,
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    b64 = lambda raw: base64.b64encode(raw).decode("ascii")  # noqa: E731
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = _scrypt(password, base64.b64decode(salt_b64), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)
