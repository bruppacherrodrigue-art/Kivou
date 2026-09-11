"""Authenticated HTTP boundary for Founder prospection actions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from signals.founder_api.access import FounderIdentityDependency
from signals.prospection_actions.contracts import (
    CONTRACT_VERSION,
    ApproveCommand,
    CorrectCommand,
    ProspectStatus,
    RejectCommand,
    SendCommand,
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


def build_prospection_actions_router(service: ProspectionActions) -> APIRouter:
    router = APIRouter(prefix="/api/founder/actions/prospection")

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

    @router.post("/send")
    def send(command: SendCommand, identity: FounderIdentityDependency):
        try:
            result = service.send(command, actor=identity.email)
        except ProspectionActionError as error:
            raise _error(error) from error
        return {
            "version": CONTRACT_VERSION,
            "request_id": result.request_id,
            "results": result.results,
            "daily_sent_count": result.daily_sent_count,
            "daily_remaining": result.daily_remaining,
        }

    return router


__all__ = ["build_prospection_actions_router"]
