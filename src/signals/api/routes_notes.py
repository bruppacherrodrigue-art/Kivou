from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from signals.api.dependencies import current_session, enforce_origin, request_now
from signals.api.errors import api_error
from signals.api.routes_feedback import _accessible_signal
from signals.engagement import notes
from signals.engagement.schema import MAXIMUM_SIGNAL_NOTE_LENGTH

router = APIRouter()


class NoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(max_length=MAXIMUM_SIGNAL_NOTE_LENGTH)
    expected_revision: int | None = Field(default=None, strict=True, ge=0)


def _response(signal_key: str, stored: notes.StoredNote | None) -> dict[str, Any]:
    return {
        "signal_id": signal_key,
        "note": None if stored is None else stored.note,
        "updated_at": None if stored is None else stored.updated_at.isoformat(),
        "revision": 0 if stored is None else stored.revision,
    }


@router.get("/signals/{signal_key}/note")
def read_note(signal_key: str, request: Request) -> dict[str, Any]:
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        _accessible_signal(connection, session, signal_key, now)
        stored = notes.get(connection, account_id=session.account_id, signal_key=signal_key)
    return _response(signal_key, stored)


@router.put("/signals/{signal_key}/note")
def write_note(signal_key: str, payload: NoteRequest, request: Request) -> dict[str, Any]:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        _accessible_signal(connection, session, signal_key, now)
        try:
            stored = notes.put(
                connection,
                account_id=session.account_id,
                signal_key=signal_key,
                note=payload.note,
                expected_revision=payload.expected_revision,
                now=now,
            )
        except notes.NoteRevisionError as error:
            raise api_error(
                409,
                error.code,
                "la note a changé ; rechargez la version enregistrée",
                note=error.note,
                revision=error.revision,
                updated_at=error.updated_at.isoformat() if error.updated_at else None,
            ) from error
    return _response(signal_key, stored)
