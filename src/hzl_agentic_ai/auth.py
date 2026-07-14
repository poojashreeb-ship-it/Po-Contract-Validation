"""Internal API-key gate.

Callers are UiPath robots on a trusted internal network, not the public
internet — a single shared-secret header is enough here; there's no per-user
identity to model, so a full OAuth/JWT setup would be solving a problem this
service doesn't have.
"""
import os
import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key")


def verify_api_key(api_key: str = Security(_api_key_header)) -> None:
    expected = os.environ["API_KEY"]
    if not secrets.compare_digest(api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
