"""Encryption at rest for stored platform credentials (ESPN espn_s2/SWID).

espn_s2 is a live session cookie for the user's ESPN account, so a leaked
database or backup must not hand those sessions out. Rows are stored as
{"v": 1, "enc": <Fernet token of the JSON>}; rows written before encryption
existed are plain dicts, read as-is and re-sealed on their next sync.
"""

import base64
import json
import logging
from functools import cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import get_settings

logger = logging.getLogger(__name__)

_VERSION = 1


@cache
def _fernet() -> Fernet:
    settings = get_settings()
    if settings.credentials_key:
        return Fernet(settings.credentials_key.encode())
    # No dedicated key: derive one from JWT_SECRET, domain-separated so it
    # never doubles as the token-signing key.
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"ffai/league-credentials/v1"
    ).derive(settings.jwt_secret.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def is_sealed(stored: dict[str, Any] | None) -> bool:
    return bool(stored) and "enc" in stored


def seal_credentials(creds: dict[str, Any] | None) -> dict[str, Any] | None:
    if not creds:
        return None
    token = _fernet().encrypt(json.dumps(creds).encode()).decode()
    return {"v": _VERSION, "enc": token}


def open_credentials(stored: dict[str, Any] | None) -> dict[str, Any]:
    """The plaintext credentials, or {} when there are none or they can't be
    decrypted (e.g. the key changed — the user must reconnect the league)."""
    if not stored:
        return {}
    if not is_sealed(stored):
        return dict(stored)  # legacy plaintext row
    try:
        return json.loads(_fernet().decrypt(stored["enc"].encode()))
    except (InvalidToken, ValueError, TypeError):
        logger.warning("Stored league credentials could not be decrypted — reconnect needed")
        return {}
