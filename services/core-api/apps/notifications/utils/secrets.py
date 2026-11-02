"""Webhook subscription secrets, sealed with AES-GCM under NOTIFICATION_SECRET_KEY, never the PII key."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

_NONCE_LEN = 12


class WebhookSecrets:
    """Seals a subscription's secret for storage and opens it to sign a delivery."""

    def key(self) -> bytes:
        key = base64.b64decode(settings.NOTIFICATION_SECRET_KEY)
        if len(key) != 32:
            raise ValueError("NOTIFICATION_SECRET_KEY must decode to exactly 32 bytes (AES-256)")
        return key

    def seal(self, secret: str) -> tuple[bytes, bytes]:
        """Returns (ciphertext, nonce)."""
        nonce = os.urandom(_NONCE_LEN)
        return AESGCM(self.key()).encrypt(nonce, secret.encode("utf-8"), None), nonce

    def open(self, ciphertext: bytes | memoryview, nonce: bytes | memoryview) -> bytes:
        """The secret's bytes, the HMAC key of every delivery."""
        return AESGCM(self.key()).decrypt(bytes(nonce), bytes(ciphertext), None)


webhook_secrets = WebhookSecrets()
