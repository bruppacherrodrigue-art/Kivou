"""Authenticated HTTP boundary for Founder prospection actions."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from signals.founder_api.access import FounderIdentityDependency
from signals.founder_api.acquisition_actions import (
    FounderAcquisitionLauncher,
    FounderAcquisitionLaunchError,
)
from signals.prospection_actions.contracts import (
    CONTRACT_VERSION,
    ApproveCommand,
    CorrectCommand,
    ProspectStatus,
    RejectCommand,
    SendCommand,
    SendRequestProgress,
)
from signals.prospection_actions.service import ProspectionActionError, ProspectionActions


def _error(error: ProspectionActionError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={
            "code": error.code,
            "message": error.message,
            "target_ids": list(error.target_ids),
        },
    )


def _public_error(value: str | None, *, limit: int) -> str | None:
    """Keep worker diagnostics useful without returning unbounded stored text."""
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized[:limit] or None


def _send_response(result: SendRequestProgress) -> dict[str, object]:
    """Serialize only the public durable-send progress contract."""
    request_id = str(result.request_id)
    return {
        "version": "founder-prospection-send-v2",
        "request_id": request_id,
        "status": result.status,
        "total_count": result.total_count,
        "processed_count": result.processed_count,
        "sent_count": result.sent_count,
        "failed_count": result.failed_count,
        "status_url": f"/api/founder/actions/prospection/send/{request_id}",
        "items": [
            {
                "target_id": str(item.target_id),
                "email_address": str(item.email_address),
                "status": item.status,
                "error_code": _public_error(item.error_code, limit=128),
                "error_message": _public_error(item.error_message, limit=200),
            }
            for item in result.items
        ],
    }


def build_prospection_actions_router(
    service: ProspectionActions,
    *,
    acquisition_launcher: FounderAcquisitionLauncher | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/founder/actions/prospection")

    if acquisition_launcher is not None:

        @router.post("/prepare", status_code=202)
        def prepare(identity: FounderIdentityDependency):
            del identity
            try:
                result = acquisition_launcher.prepare()
            except FounderAcquisitionLaunchError as error:
                raise HTTPException(
                    status_code=error.status_code,
                    detail={
                        "code": error.code,
                        "message": error.message,
                        "target_ids": [],
                    },
                ) from error
            return {
                "version": "founder-prospection-prepare-v1",
                "status": "accepted",
                "prepared_today_count": result.prepared_today_count,
                "daily_pending_cap": result.daily_pending_cap,
            }

    @router.get("/list")
    def list_targets(
        identity: FounderIdentityDependency,
        status: Annotated[ProspectStatus | None, Query()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=25)] = 25,
    ):
        del identity
        return service.list(status=status, page=page, page_size=page_size)

    @router.post("/approve")
    def approve(command: ApproveCommand, identity: FounderIdentityDependency):
        try:
            target = service.approve(command, actor=identity.email)
        except ProspectionActionError as error:
            raise _error(error) from error
        return {"version": CONTRACT_VERSION, "target": target}

    @router.post("/correct")
    def correct(command: CorrectCommand, identity: FounderIdentityDependency):
        try:
            result = service.correct(command, actor=identity.email)
        except ProspectionActionError as error:
            raise _error(error) from error
        return {
            "version": CONTRACT_VERSION,
            "target": result.target,
            "token_reissued": result.token_reissued,
            "email_reverified": result.email_reverified,
            "directory_updated": result.directory_updated,
        }

    @router.post("/reject")
    def reject(command: RejectCommand, identity: FounderIdentityDependency):
        try:
            result = service.reject(command, actor=identity.email)
        except ProspectionActionError as error:
            raise _error(error) from error
        return {
            "version": CONTRACT_VERSION,
            "target": result.target,
            "directory_effect": result.directory_effect,
        }

    @router.post("/send", status_code=202)
    def send(command: SendCommand, identity: FounderIdentityDependency):
        try:
            result = service.enqueue_send(command, actor=identity.email)
        except ProspectionActionError as error:
            raise _error(error) from error
        return _send_response(result)

    @router.get("/send/{request_id}")
    def send_progress(request_id: UUID, identity: FounderIdentityDependency):
        del identity
        try:
            result = service.send_progress(str(request_id))
        except ProspectionActionError as error:
            raise _error(error) from error
        return _send_response(result)

    return router


__all__ = ["build_prospection_actions_router"]
