import base64

import pytest
from cryptography.exceptions import InvalidTag

from app.evidence_crypto import decrypt_evidence, encrypt_evidence, load_evidence_key


def test_evidence_envelope_is_authenticated_and_not_plaintext(tmp_path):
    key = b"k" * 32
    name = "track-1.jpg.enc"
    plaintext = b"camera-derived-jpeg-bytes"
    path = tmp_path / name
    path.write_bytes(encrypt_evidence(plaintext, name, key))
    assert plaintext not in path.read_bytes()
    assert decrypt_evidence(path, key) == plaintext
    tampered = bytearray(path.read_bytes())
    tampered[-1] ^= 1
    path.write_bytes(tampered)
    with pytest.raises(InvalidTag):
        decrypt_evidence(path, key)


def test_evidence_key_must_be_exactly_256_bits(tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text(
        base64.urlsafe_b64encode(b"short").decode("ascii"), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_evidence_key(str(key_file))
