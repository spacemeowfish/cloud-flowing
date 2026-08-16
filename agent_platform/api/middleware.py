"""Server-owned browser identity and unified API exception responses."""

from collections.abc import Awaitable, Callable
import logging
import secrets

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
from agent_platform.api.auth import BROWSER_SESSION_COOKIE, DEVELOPER_SESSION_COOKIE
from agent_platform.models import ErrorResponse


class AuthenticationContextMiddleware(BaseHTTPMiddleware):
    """Derive both task ownership and role from server-issued cookies."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        browser_session = request.cookies.get(BROWSER_SESSION_COOKIE)
        created_session = False
        if not browser_session:
            browser_session = secrets.token_urlsafe(24)
            created_session = True
        developer_token = request.cookies.get(DEVELOPER_SESSION_COOKIE)
        auth = request.app.state.developer_sessions
        request.state.role = "developer" if auth.is_valid(developer_token) else "user"
        request.state.session_id = browser_session
        response = await call_next(request)
        if created_session:
            response.set_cookie(
                BROWSER_SESSION_COOKIE,
                browser_session,
                httponly=True,
                samesite="strict",
                secure=False,
                path="/",
            )
        logging.getLogger("agent_platform.api.access").info(
            "%s %s -> %s", request.method, request.url.path, response.status_code
        )
        return response


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


__all__ = ["AuthenticationContextMiddleware", "register_error_handlers"]
