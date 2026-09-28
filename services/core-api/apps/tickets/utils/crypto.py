"""
AES-GCM encryption for `pii_quarantine.ciphertext`. Key comes from
settings.PII_ENCRYPTION_KEY (env-sourced), never from the database — the
whole point of quarantine is that compromising the DB alone isn't enough
to read raw PII (spec §0: "Lưu PII raw — Được, có mã hóa + TTL").
"""

from __future__ import annotations

import base64
import os
import uuid
from dataclasses import dataclass
from datetime import timedelta

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.utils import timezone

_NONCE_LEN = 12  # 96-bit nonce, standard for AES-GCM


def _key() -> bytes:
    key = base64.b64decode(settings.PII_ENCRYPTION_KEY)
    if len(key) != 32:
        raise ValueError("PII_ENCRYPTION_KEY must decode to exactly 32 bytes (AES-256)")
    return key


def encrypt(plaintext: str) -> tuple[bytes, bytes]:
    """Returns (ciphertext, nonce)."""
    aesgcm = AESGCM(_key())
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return ciphertext, nonce


def decrypt(ciphertext: bytes, nonce: bytes) -> str:
    aesgcm = AESGCM(_key())
    return aesgcm.decrypt(bytes(nonce), bytes(ciphertext), associated_data=None).decode("utf-8")


@dataclass(frozen=True)
class QuarantineEntry:
    ref: uuid.UUID
    ciphertext: bytes
    nonce: bytes
    expires_at: object  # datetime, kept loosely typed to avoid importing models here


def build_quarantine_entries(placeholder_map: dict[str, str]) -> dict[str, QuarantineEntry]:
    """Encrypts every real value in `placeholder_map` and returns
    placeholder -> QuarantineEntry, ready to persist as PiiQuarantine rows.
    TTL is settings.PII_QUARANTINE_TTL_HOURS (default 72h, spec §3.1)."""

    ttl = timedelta(hours=settings.PII_QUARANTINE_TTL_HOURS)
    expires_at = timezone.now() + ttl

    out: dict[str, QuarantineEntry] = {}
    for placeholder, real_value in placeholder_map.items():
        ciphertext, nonce = encrypt(real_value)
        out[placeholder] = QuarantineEntry(
            ref=uuid.uuid4(), ciphertext=ciphertext, nonce=nonce, expires_at=expires_at
        )
    return out
