"""Tiện ích nhỏ dùng chung: id có thứ tự thời gian, thời gian, mã hoá, băm mật khẩu."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from datetime import UTC, datetime

_last_ms = 0
_counter = 0


def new_id() -> str:
    """Id sắp xếp được theo thời gian (dùng làm con trỏ cho live log): 13 số ms + 4 số đếm + 6 hex."""
    global _last_ms, _counter
    ms = int(time.time() * 1000)
    if ms == _last_ms:
        _counter += 1
    else:
        _last_ms, _counter = ms, 0
    return f"{ms:013d}{_counter:04d}{secrets.token_hex(3)}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


# ------------------------------------------------------------------ mật khẩu (scrypt, stdlib)
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(digest, expected)


# ------------------------------------------------------------------ AES-GCM cho secret store local
def _master_key(master: str) -> bytes:
    # Chấp nhận khoá base64 32 byte hoặc chuỗi bất kỳ (được băm thành 32 byte).
    try:
        raw = base64.b64decode(master, validate=True)
        if len(raw) == 32:
            return raw
    except ValueError:
        pass
    return hashlib.sha256(master.encode()).digest()


def encrypt(master: str, plaintext: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    ct = AESGCM(_master_key(master)).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt(master: str, token: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    raw = base64.b64decode(token)
    return AESGCM(_master_key(master)).decrypt(raw[:12], raw[12:], None).decode()
