from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator

from signals.accounts import data_rights
from signals.api.dependencies import current_session, enforce_origin, request_now

router = APIRouter()


class DeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str

    @field_validator("confirmation")
    @classmethod
    def confirmed(cls, value: str) -> str:
        if value != "SUPPRIMER":
            raise ValueError("saisissez SUPPRIMER pour confirmer")
        return value


@router.get("/account/export")
def export_account(request: Request, response: Response) -> dict[str, object]:
    with request.app.state.engine.connect() as connection:
        session = current_session(request, connection, request_now(request))
        payload = data_rights.export_account(connection, account_id=session.account_id)
    response.headers["Content-Disposition"] = 'attachment; filename="kivou-account-export.json"'
    return payload


@router.post("/account/deletion", status_code=202)
def delete_account(payload: DeletionRequest, request: Request) -> dict[str, str]:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        scheduled = data_rights.request_deletion(
            connection, account_id=session.account_id, now=now
        )
    return {"scheduled_for": scheduled.isoformat()}
