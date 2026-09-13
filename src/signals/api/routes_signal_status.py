"""Revision-checked, reversible account workflow for accessible signals."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from signals.api.dependencies import current_session, enforce_origin, request_now
from signals.api.errors import api_error
from signals.api.routes_feedback import _accessible_signal, _context, interaction_block
from signals.client_value.company_identity import resolve_company_subject
from signals.companies.service import company_keys_for_signals
from signals.engagement import company, feedback, status

router = APIRouter()


class SignalStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["new", "saved", "contacted", "ignored"]
    expected_revision: int = Field(strict=True, ge=0)


@router.put("/signals/{signal_key}/status")
def write_status(signal_key: str, payload: SignalStatusRequest, request: Request) -> dict[str, Any]:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        item = _accessible_signal(connection, session, signal_key, now)
        try:
            stored = status.set_status(
                connection,
                account_id=session.account_id,
                context=_context(item),
                status=payload.status,
                expected_revision=payload.expected_revision,
                now=now,
                user_id=session.user_id,
            )
        except status.StatusConflict as error:
            raise api_error(
                409,
                "status_conflict",
                str(error),
                status=error.status,
                revision=error.revision,
                updated_at=error.updated_at.isoformat(),
            ) from error
        if payload.status == "contacted":
            company_key = company_keys_for_signals(
                connection,
                signal_keys=(signal_key,),
            ).get(signal_key)
            if company_key is not None:
                subject = resolve_company_subject(
                    connection, account_id=session.account_id, company_key=company_key, now=now
                )
                company.mark_contacted_if_pending(
                    connection,
                    account_id=session.account_id,
                    company_key=subject.private_subject_key,
                    now=now,
                )
        historical = feedback.get_feedback(
            connection,
            account_id=session.account_id,
            signal_key=signal_key,
        )
    return {
        "signal_id": signal_key,
        "status": stored.status,
        "revision": stored.revision,
        "updated_at": stored.updated_at.isoformat(),
        "interaction": interaction_block(historical),
    }
