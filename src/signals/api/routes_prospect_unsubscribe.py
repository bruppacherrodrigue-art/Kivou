"""Public confirmation boundary for signed assisted unsubscribe links."""

from __future__ import annotations

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from signals.api.dependencies import request_now

router = APIRouter()


def _page(*, token: str, confirmed: bool) -> HTMLResponse:
    title = "Désinscription confirmée" if confirmed else "Ne plus recevoir ces e-mails"
    action = html.escape(f"/unsubscribe/{token}", quote=True)
    body = (
        "<p>Votre adresse professionnelle a été retirée de nos prochains envois.</p>"
        if confirmed
        else (
            "<p>Confirmez pour ne plus recevoir les e-mails de prospection Kivou.</p>"
            f'<form method="post" action="{action}"><button type="submit">Confirmer</button></form>'
        )
    )
    return HTMLResponse(
        "<!doctype html><html lang=\"fr\"><meta charset=\"utf-8\">"
        f"<meta name=\"robots\" content=\"noindex,nofollow\"><title>{title}</title>"
        f"<main><h1>{title}</h1>{body}</main></html>",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.get("/unsubscribe/{token}", include_in_schema=False)
def unsubscribe_confirmation(token: str, request: Request) -> HTMLResponse:
    service = getattr(request.app.state, "prospect_unsubscribe_service", None)
    if service is None:
        return HTMLResponse("Lien indisponible", status_code=404)
    try:
        service.verify(token, at=request_now(request))
    except ValueError:
        return HTMLResponse("Lien invalide", status_code=404)
    return _page(token=token, confirmed=False)


@router.post("/unsubscribe/{token}", include_in_schema=False)
def unsubscribe(token: str, request: Request) -> HTMLResponse:
    service = getattr(request.app.state, "prospect_unsubscribe_service", None)
    if service is None:
        return HTMLResponse("Lien indisponible", status_code=404)
    try:
        service.unsubscribe(token, at=request_now(request))
    except ValueError:
        return HTMLResponse("Lien invalide", status_code=404)
    return _page(token=token, confirmed=True)


__all__ = ["router"]
