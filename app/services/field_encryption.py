"""Field-Level-Encryption fuer sensible Steckbrief-Felder (CD5).

Schluessel-Ableitung: HKDF(master_key, salt=b"steckbrief-v1",
    info=b"{entity_type}:{field_name}") → 32 Bytes → Fernet-Key.
Ciphertext-Format: "v1:<fernet-token>" — key_id als Praefix fuer
spaetere Rotation (Rotation-Job = v1.1, Format ist rotation-faehig).
"""
from __future__ import annotations

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class DecryptionError(Exception):
    """Entschluesselung gescheitert (falscher Key, beschaedigter Token,
    unbekannte key_id)."""


def _derive_fernet(entity_type: str, field: str, master_key: str) -> Fernet:
    """Leitet aus dem Master-Key per HKDF einen Fernet-Schluessel ab."""
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"steckbrief-v1",
        info=f"{entity_type}:{field}".encode(),
    )
    derived = kdf.derive(master_key.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def _master_key() -> str:
    from app.config import settings  # lazy, vermeidet Zirkular-Import

    return settings.steckbrief_field_key or settings.secret_key


def encrypt_field(
    plaintext: str, *, entity_type: str, field: str, key_id: str = "v1"
) -> str:
    """Verschluesselt `plaintext` und gibt "v1:<fernet-token>" zurueck."""
    if ":" in key_id:
        raise ValueError(f"key_id darf kein ':' enthalten: {key_id!r}")
    fernet = _derive_fernet(entity_type, field, _master_key())
    token: bytes = fernet.encrypt(plaintext.encode("utf-8"))
    return f"{key_id}:{token.decode('ascii')}"


def decrypt_field(
    ciphertext: str, *, entity_type: str, field: str
) -> str:
    """Entschluesselt und gibt Klartext zurueck.

    Raises DecryptionError bei ungueltigem Token oder falschem Key.
    """
    if ":" not in ciphertext:
        raise DecryptionError(
            f"Unbekanntes Ciphertext-Format (kein key_id-Praefix): {ciphertext[:20]!r}"
        )
    _key_id, _, token_str = ciphertext.partition(":")
    # key_id wird fuer kuenftige Rotation genutzt; v1 kennt nur einen Key.
    try:
        fernet = _derive_fernet(entity_type, field, _master_key())
        return fernet.decrypt(token_str.encode("ascii")).decode("utf-8")
    except Exception as exc:
        # Fernet.decrypt wirft InvalidToken bei falschem Key / beschaedigtem
        # Token; der breite Exception-Catch faengt zusaetzliche Ueberraschungen
        # (z. B. base64-ValueError bei muell-Eingabe) in dieselbe Semantik.
        raise DecryptionError(str(exc)) from exc
