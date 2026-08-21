"""RuoYi JWT gateway gate and unified API exception responses.

The gate implements ``docs/contracts/ruoyi-auth-gateway.md`` §5: every data or
action endpoint requires a valid RuoYi bearer token; only ``GET /health`` and
the static page shells/assets load anonymously. Any failure (missing header,
bad signature, revoked session, auth backend outage) yields the same
``auth_required`` 401 — reasons stay in server logs.
"""

from collections.abc import Awaitable, Callable
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from agent_platform.core.errors import (
    AgentPlatformError,
    NoMicrophoneError,
    PermissionDeniedError,
    TaskNotFoundError,
    VoiceServiceBusyError,
    VoiceTranscriptionTimeoutError,
)
from agent_platform.core.ruoyi_auth import AuthenticatedIdentity, RuoYiAuthenticator
from agent_platform.models import ErrorResponse

AUTH_REQUIRED_CODE = "auth_required"

_STATIC_DIRECTORY = (Path(__file__).resolve().parents[1] / "static").resolve()
# Page shells load anonymously (contract §5); app.js's login gate enforces
# authentication and the developer role client-side while every data or
# action endpoint stays behind the bearer-token gate.
_PAGE_SHELL_PATHS = {"", "/", "/developer", "/developer/"}


def _unauthorized() -> JSONResponse:
    payload = ErrorResponse(code=AUTH_REQUIRED_CODE, message="Authentication required", retryable=False)
    return JSONResponse(status_code=401, content=payload.model_dump(mode="json"))


def _is_anonymous_get(path: str) -> bool:
    """GET /health plus static page shells and assets (contract §5 clarification)."""

    if path == "/health":
        return True
    if path in _PAGE_SHELL_PATHS:
        return True
    candidate = (_STATIC_DIRECTORY / path.lstrip("/")).resolve()
    return candidate.is_file() and candidate.is_relative_to(_STATIC_DIRECTORY)


class AuthenticationContextMiddleware(BaseHTTPMiddleware):
    """Derive both task ownership and role from the verified RuoYi identity."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.method in {"GET", "HEAD"} and _is_anonymous_get(request.url.path):
            self._apply(request, None)
            response = await call_next(request)
        else:
            authenticator: RuoYiAuthenticator | None = getattr(request.app.state, "ruoyi_authenticator", None)
            identity: AuthenticatedIdentity | None = None
            if authenticator is not None:
                try:
                    identity = await authenticator.authenticate(request.headers.get("Authorization"))
                except Exception:
                    # Redis outage or any backend failure fails closed; the
                    # reason is server-side only.
                    logging.getLogger("agent_platform.ruoyi_auth").warning(
                        "auth backend failure for %s %s; failing closed",
                        request.method,
                        request.url.path,
                        exc_info=True,
                    )
            if identity is None:
                response = _unauthorized()
            else:
                self._apply(request, identity)
                response = await call_next(request)
        logging.getLogger("agent_platform.api.access").info(
            "%s %s -> %s", request.method, request.url.path, response.status_code
        )
        return response

    @staticmethod
    def _apply(request: Request, identity: AuthenticatedIdentity | None) -> None:
        if identity is None:
            request.state.role = "user"
            request.state.session_id = ""
            request.state.username = ""
            request.state.user_id = 0
        else:
            request.state.role = identity.role
            request.state.session_id = identity.session_id
            request.state.username = identity.username
            request.state.user_id = identity.user_id


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AgentPlatformError)
    async def platform_error(_: Request, exc: AgentPlatformError) -> JSONResponse:
        if isinstance(exc, TaskNotFoundError):
            status = 404
        elif isinstance(exc, PermissionDeniedError):
            status = 403
        elif isinstance(exc, NoMicrophoneError):
            status = 404
        elif isinstance(exc, VoiceServiceBusyError):
            status = 409
        elif isinstance(exc, VoiceTranscriptionTimeoutError):
            status = 504
        else:
            status = 409 if exc.retryable else 400
        payload = ErrorResponse(code=exc.code, message=exc.detail, retryable=exc.retryable)
        return JSONResponse(status_code=status, content=payload.model_dump(mode="json"))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        payload = ErrorResponse(
            code=f"http_{exc.status_code}",
            message=str(exc.detail),
            retryable=exc.status_code in {409, 429, 502, 503, 504},
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {"msg": "Invalid request"}
        payload = ErrorResponse(code="request_validation_error", message=str(first.get("msg", "Invalid request")))
        return JSONResponse(status_code=422, content=payload.model_dump(mode="json"))


__all__ = ["AUTH_REQUIRED_CODE", "AuthenticationContextMiddleware", "register_error_handlers"]
