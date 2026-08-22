"""First-party click attribution: fixed redirect, never authentication."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from signals.api.config import ATTRIBUTION_COOKIE_NAME
from signals.api.dependencies import request_now
from signals.api.errors import api_error

router = APIRouter()


@router.get("/a/{token}", include_in_schema=False)
def attribution_click(token: str, request: Request) -> RedirectResponse:
    service = getattr(request.app.state, "conversion_attribution_service", None)
    if service is None:
        raise api_error(404, "attribution_not_found", "lien introuvable")
    try:
        result = service.record_click(token, at=request_now(request))
    except ValueError as error:
        raise api_error(404, "attribution_not_found", "lien introuvable") from error

    response = RedirectResponse(url="/signup", status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.set_cookie(
        ATTRIBUTION_COOKIE_NAME,
        token,
        httponly=True,
        secure=request.app.state.config.cookie_secure,
        samesite="lax",
        path="/auth/signup",
        expires=result.expires_at,
    )
    return response


__all__ = ["router"]
