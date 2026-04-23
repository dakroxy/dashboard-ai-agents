"""Story 1.7 — Unit-Tests fuer app/services/field_encryption.py.

Reine Logik-Tests ohne TestClient oder DB. Der Master-Key kommt aus dem
Test-SECRET_KEY (in conftest.py gesetzt, Fallback-Zweig von `_master_key`).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use")
os.environ.setdefault("POSTGRES_PASSWORD", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("IMPOWER_BEARER_TOKEN", "")

from app.services.field_encryption import (  # noqa: E402
    DecryptionError,
    decrypt_field,
    encrypt_field,
)
from app.services.steckbrief_write_gate import (  # noqa: E402
    _json_safe_for_provenance,
)


# ---------------------------------------------------------------------------
# Format + Roundtrip
# ---------------------------------------------------------------------------

def test_encrypt_produces_v1_prefix():
    ct = encrypt_field(
        "1234", entity_type="object", field="entry_code_main_door"
    )
    assert ct.startswith("v1:")


def test_roundtrip_plaintext():
    ct = encrypt_field(
        "1234-5678", entity_type="object", field="entry_code_main_door"
    )
    assert (
        decrypt_field(ct, entity_type="object", field="entry_code_main_door")
        == "1234-5678"
    )


def test_roundtrip_special_chars():
    plain = "A#1!@9-X"
    ct = encrypt_field(
        plain, entity_type="object", field="entry_code_garage"
    )
    assert (
        decrypt_field(ct, entity_type="object", field="entry_code_garage")
        == plain
    )


def test_empty_roundtrip():
    ct = encrypt_field(
        "0", entity_type="object", field="entry_code_main_door"
    )
    assert (
        decrypt_field(ct, entity_type="object", field="entry_code_main_door")
        == "0"
    )


# ---------------------------------------------------------------------------
# HKDF-Isolation
# ---------------------------------------------------------------------------

def test_different_fields_different_ciphertext():
    """Gleicher plaintext, unterschiedliche field-Parameter → unterschiedliche
    Ableitung → nicht nur unterschiedliche Tokens, sondern auch gegenseitig
    nicht entschluesselbar."""
    plain = "SAME-CODE-42"
    ct_main = encrypt_field(
        plain, entity_type="object", field="entry_code_main_door"
    )
    ct_garage = encrypt_field(
        plain, entity_type="object", field="entry_code_garage"
    )
    assert ct_main != ct_garage
    with pytest.raises(DecryptionError):
        decrypt_field(
            ct_main, entity_type="object", field="entry_code_garage"
        )


def test_different_entity_types_different_ciphertext():
    plain = "CROSS-ENTITY"
    ct_obj = encrypt_field(
        plain, entity_type="object", field="entry_code_main_door"
    )
    ct_unit = encrypt_field(
        plain, entity_type="unit", field="entry_code_main_door"
    )
    assert ct_obj != ct_unit
    with pytest.raises(DecryptionError):
        decrypt_field(
            ct_obj, entity_type="unit", field="entry_code_main_door"
        )


def test_fernet_random_iv():
    """Zweimal encrypten ergibt zwei unterschiedliche Tokens — entscheidend
    fuer die Noop-Check-Semantik im Write-Gate."""
    plain = "DUPLICATE"
    ct_a = encrypt_field(
        plain, entity_type="object", field="entry_code_main_door"
    )
    ct_b = encrypt_field(
        plain, entity_type="object", field="entry_code_main_door"
    )
    assert ct_a != ct_b


# ---------------------------------------------------------------------------
# Fehlerpfade
# ---------------------------------------------------------------------------

def test_decrypt_wrong_format_raises():
    with pytest.raises(DecryptionError):
        decrypt_field(
            "no-colon-here",
            entity_type="object",
            field="entry_code_main_door",
        )


def test_decrypt_tampered_token_raises():
    ct = encrypt_field(
        "VALID", entity_type="object", field="entry_code_main_door"
    )
    prefix, _, token = ct.partition(":")
    # Letztes Zeichen im Token durch ein anderes gueltiges base64-Zeichen
    # ersetzen — MAC-Check muss scheitern.
    flip_char = "a" if token[-1] != "a" else "b"
    tampered = f"{prefix}:{token[:-1]}{flip_char}"
    with pytest.raises(DecryptionError):
        decrypt_field(
            tampered, entity_type="object", field="entry_code_main_door"
        )


# ---------------------------------------------------------------------------
# Provenance-Marker bleibt {"encrypted": True}
# ---------------------------------------------------------------------------

def test_key_in_provenance_marker():
    """Story 1.2 hat den `{"encrypted": True}`-Marker eingefuehrt — Story 1.7
    darf ihn nicht brechen."""
    assert _json_safe_for_provenance(
        "object", "entry_code_main_door", "anything"
    ) == {"encrypted": True}
    assert _json_safe_for_provenance(
        "object", "entry_code_garage", "v1:abc"
    ) == {"encrypted": True}


# ---------------------------------------------------------------------------
# key_id-Praefix
# ---------------------------------------------------------------------------

def test_encrypt_key_id_default():
    ct = encrypt_field(
        "FOO", entity_type="object", field="entry_code_main_door"
    )
    assert ct.split(":", 1)[0] == "v1"


def test_encrypt_custom_key_id():
    ct = encrypt_field(
        "FOO",
        entity_type="object",
        field="entry_code_main_door",
        key_id="v2",
    )
    assert ct.startswith("v2:")


def test_decrypt_with_custom_key_id():
    """key_id ist heute nur ein Praefix — v1 und v2 leiten denselben Schluessel
    ab, Roundtrip funktioniert unabhaengig vom Praefix."""
    ct = encrypt_field(
        "ROUND",
        entity_type="object",
        field="entry_code_main_door",
        key_id="v2",
    )
    assert (
        decrypt_field(
            ct, entity_type="object", field="entry_code_main_door"
        )
        == "ROUND"
    )
