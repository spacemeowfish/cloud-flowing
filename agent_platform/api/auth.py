"""Authentication view and developer authorization dependency.

Login itself lives in RuoYi; the gateway middleware verifies the bearer token
before any route runs, so this module only exposes the already-verified
identity and gates developer routes.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

__all__ = ["AuthenticationView", "require_developer", "router"]


class AuthenticationView(BaseModel):
    role: str = Field(..., description="Verified role: user or developer")
    username: str = Field(..., description="RuoYi username (display/audit identity)")
    user_id: int = Field(..., ge=0, description="RuoYi userId owning this account's data space")


def require_developer(request: Request) -> None:
    if request.state.role != "developer":
        raise HTTPException(status_code=403, detail="Developer login required")


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/me", response_model=AuthenticationView)
async def authentication_status(request: Request) -> AuthenticationView:
    return AuthenticationView(
        role=str(getattr(request.state, "role", "user")),
        username=str(getattr(request.state, "username", "")),
        user_id=int(getattr(request.state, "user_id", 0)),
    )
