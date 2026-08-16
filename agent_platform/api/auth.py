"""Developer login routes and authorization dependency."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from agent_platform.core.developer_auth import DeveloperSessionService


BROWSER_SESSION_COOKIE = "agent_browser_session"
DEVELOPER_SESSION_COOKIE = "agent_developer_session"


class DeveloperLogin(BaseModel):
    password: str = Field(..., min_length=1, max_length=1024)


class AuthenticationView(BaseModel):
    role: str
    developer_configured: bool


def _auth(request: Request) -> DeveloperSessionService:
    return request.app.state.developer_sessions


def require_developer(request: Request) -> None:
    if request.state.role != "developer":
        raise HTTPException(status_code=403, detail="Developer login required")


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/me", response_model=AuthenticationView)
async def authentication_status(request: Request) -> AuthenticationView:
    return AuthenticationView(role=request.state.role, developer_configured=_auth(request).configured)


@router.post("/developer/login", response_model=AuthenticationView)
async def developer_login(payload: DeveloperLogin, request: Request, response: Response) -> AuthenticationView:
    auth = _auth(request)
    if not auth.configured:
        raise HTTPException(status_code=503, detail="Developer password is not configured")
    token = auth.login(payload.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid developer password")
    response.set_cookie(
        DEVELOPER_SESSION_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )
    return AuthenticationView(role="developer", developer_configured=True)


@router.post("/logout", response_model=AuthenticationView)
async def logout(request: Request, response: Response) -> AuthenticationView:
    auth = _auth(request)
    auth.logout(request.cookies.get(DEVELOPER_SESSION_COOKIE))
    response.delete_cookie(DEVELOPER_SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return AuthenticationView(role="user", developer_configured=auth.configured)


__all__ = [
    "BROWSER_SESSION_COOKIE",
    "DEVELOPER_SESSION_COOKIE",
    "require_developer",
    "router",
]
