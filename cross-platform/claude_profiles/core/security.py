"""Password hashing for the simple launch lock.

This is a lock, not encryption: it stops the loader and launchers from opening
a profile without the password, but the profile's files stay readable by your
user account.
"""

import base64
import hashlib
import hmac
import os

ALGO = "pbkdf2-sha256"
ITERATIONS = 300_000


def hash_password(password: str) -> dict:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return {
        "algo": ALGO,
        "iterations": ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "hash": base64.b64encode(digest).decode("ascii"),
    }


def verify_password(password: str, record: dict) -> bool:
    if not record or record.get("algo") != ALGO:
        return False
    try:
        salt = base64.b64decode(record["salt"])
        expected = base64.b64decode(record["hash"])
        iterations = int(record["iterations"])
    except (KeyError, ValueError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)
