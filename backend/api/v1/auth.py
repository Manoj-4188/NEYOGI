"""``/api/v1/auth/*`` -- officer sign-in.

The public dashboard needs no account. This exists only to mint the bearer
token the officer console presents.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel, Field

from backend import db
from backend.security import Principal, create_access_token, current_principal, authenticate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str
    role: str


@router.post("/login", response_model=TokenResponse, summary="Officer sign-in")
async def login(payload: LoginRequest) -> TokenResponse:
    try:
        principal = await authenticate(payload.username, payload.password)
    except db.DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Authentication store is unreachable: {exc}",
        ) from exc

    if principal is None:
        logger.warning("Failed sign-in for %r", payload.username)
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expires_in = create_access_token(principal.username, principal.role)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        username=principal.username,
        role=principal.role,
    )


@router.get("/me", summary="Identity behind the current token")
async def me(
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict:
    return {"username": principal.username, "role": principal.role}
