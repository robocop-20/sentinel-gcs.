"""Authenticated encryption envelope for camera-derived object evidence."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

EVIDENCE_MAGIC = b"SNTLENC1"


def load_evidence_key(path: str) -> bytes:
    try:
        encoded = Path(path).read_text(encoding="utf-8").strip()
        key = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("Evidence encryption key is unavailable or invalid") from exc
    if len(key) != 32:
        raise ValueError("Evidence encryption key must decode to 32 bytes")
    return key


def encrypt_evidence(data: bytes, name: str, key: bytes) -> bytes:
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, data, name.encode("utf-8"))
    return EVIDENCE_MAGIC + nonce + ciphertext


def decrypt_evidence(path: Path, key: bytes) -> bytes:
    payload = path.read_bytes()
    if len(payload) < len(EVIDENCE_MAGIC) + 12 + 16 or not payload.startswith(
        EVIDENCE_MAGIC
    ):
        raise ValueError("Evidence envelope is invalid")
    offset = len(EVIDENCE_MAGIC)
    nonce, ciphertext = payload[offset : offset + 12], payload[offset + 12 :]
    return AESGCM(key).decrypt(nonce, ciphertext, path.name.encode("utf-8"))
