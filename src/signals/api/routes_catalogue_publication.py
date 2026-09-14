"""Narrow server-to-server company publication; never a customer entitlement bypass."""

import hmac

from fastapi import APIRouter, HTTPException, Request, Response

from signals.api.dependencies import request_now
from signals.supplier_directory.catalogue_publication import CatalogueSnapshot, build_snapshot

router = APIRouter()


@router.get("/internal/company-catalogue", response_model=CatalogueSnapshot)
def catalogue_publication(request: Request, response: Response) -> CatalogueSnapshot:
    config = request.app.state.config
    token = config.catalogue_publication_token
    supplied = request.headers.get("Authorization", "")
    if (
        config.acquisition_environment != "PRODUCTION"
        or not token
        or not 32 <= len(token) <= 256
        or len(supplied) > 300
        or not hmac.compare_digest(supplied.encode("utf-8"), f"Bearer {token}".encode())
    ):
        raise HTTPException(status_code=404, detail="Not found")
    response.headers["Cache-Control"] = "no-store"
    with request.app.state.engine.connect() as connection:
        return build_snapshot(connection, now=request_now(request))
