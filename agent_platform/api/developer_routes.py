"""Developer-only lightweight diagnostics."""

from fastapi import APIRouter, Depends, Request

from agent_platform.api.auth import require_developer


router = APIRouter(prefix="/developer", tags=["developer"], dependencies=[Depends(require_developer)])


@router.get("/logs")
async def recent_logs(request: Request) -> dict[str, object]:
    records = request.app.state.recent_logs.recent()
    return {"items": records, "count": len(records), "limit": 200}


__all__ = ["router"]
