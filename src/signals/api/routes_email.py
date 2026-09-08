"""Authenticated requests for email proof and explicit, one-time proof consumption."""
from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from signals.accounts import email_verification as verification
from signals.accounts import service as accounts
from signals.accounts.schema import auth_session, auth_user
from signals.accounts.tokens import token_hash
from signals.accounts.verification_delivery import build_verification_message
from signals.api.config import SESSION_COOKIE_NAME
from signals.api.dependencies import current_session, enforce_origin, request_now
from signals.api.errors import api_error
from signals.api.routes_auth import set_session_cookie
from signals.runtime_events import emit_delivery_event

router = APIRouter()


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class EmailProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def _locked_email_session(request: Request, connection: sa.Connection, now):
    """Serialize identity writers before reading current authorization.

    A prior unlocked session read can resume after a revocation. Lock order
    matches verification, password recovery and delivery: user, then child rows.
    The preliminary lookup identifies locks only; it does not authorize anything.
    """
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    reference = connection.execute(sa.select(auth_session.c.session_id, auth_session.c.user_id)
                                   .where(auth_session.c.token_hash == token_hash(raw))).first() if raw else None
    if reference is None:
        raise api_error(401, "not_authenticated", "authentification requise")
    user_id = connection.scalar(sa.select(auth_user.c.user_id).where(
        auth_user.c.user_id == reference.user_id, auth_user.c.is_active.is_(True),
    ).with_for_update())
    if user_id is None:
        raise api_error(401, "not_authenticated", "authentification requise")
    connection.execute(sa.select(auth_session.c.session_id).where(
        auth_session.c.session_id == reference.session_id,
        auth_session.c.user_id == user_id,
    ).with_for_update()).first()
    return current_session(request, connection, now)


@router.get("/auth/email")
def email_state(request: Request, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, request_now(request))
        return verification.state(connection, user_id=session.user_id)


@router.post("/auth/email/request")
def request_email(payload: EmailRequest, request: Request, response: Response) -> dict:
    config = request.app.state.config
    enforce_origin(request, config)
    response.headers["Cache-Control"] = "no-store"
    now = request_now(request)
    gateway = getattr(request.app.state, "email_verification_gateway", None)
    try:
        with request.app.state.engine.begin() as connection:
            session = _locked_email_session(request, connection, now)
            if gateway is None or not config.public_site_url:
                raise api_error(503, "email_verification_unavailable",
                                "L'envoi est indisponible. Réessayez plus tard.")
            proof = verification.request_verification(
                connection, user_id=session.user_id, email=payload.email, now=now,
            )
    except accounts.EmailAlreadyUsed as error:
        raise api_error(409, "email_already_used", "Cette adresse ne peut pas être utilisée.") from error
    except verification.EmailProofCooldown as error:
        raise api_error(429, "email_verification_cooldown",
                        "Patientez une minute avant de demander un nouveau lien.") from error
    # Commit the proof before sending. A failed/uncertain SMTP attempt remains unverified.
    try:
        gateway.send(build_verification_message(email=proof.email, token=proof.token,
                                               origin=config.public_site_url))
    except Exception:  # noqa: BLE001 - SMTP exceptions may contain credentials or recipients.
        emit_delivery_event(channel="email_verification", status="failed",
                            code="unexpected_error", retryable=True, attempt=1,
                            account_ref=session.account_id)
        raise api_error(503, "email_verification_unavailable",
                        "Le mail n'a pas pu être confirmé comme envoyé. Réessayez dans une minute.") from None
    emit_delivery_event(channel="email_verification", status="submitted",
                        code="smtp_submission_accepted", retryable=False, attempt=1,
                        account_ref=session.account_id)
    return {"status": "sent"}


@router.post("/auth/email/verify")
def verify_email(payload: EmailProof, request: Request, response: Response) -> dict:
    config = request.app.state.config
    enforce_origin(request, config)
    now = request_now(request)
    try:
        with request.app.state.engine.begin() as connection:
            user_id = verification.verify(connection, token=payload.token, now=now)
            session = accounts.open_session(connection, user_id=user_id, now=now,
                                            session_ttl=config.session_ttl)
    except verification.InvalidEmailProof as error:
        raise api_error(400, "invalid_email_verification",
                        "Ce lien est invalide, expiré ou déjà utilisé. Demandez un nouveau lien.") from error
    except (accounts.EmailAlreadyUsed, sa.exc.IntegrityError) as error:
        raise api_error(409, "email_already_used", "Cette adresse ne peut pas être utilisée.") from error
    response.headers["Cache-Control"] = "no-store"
    set_session_cookie(response, request, session)
    return {"status": "verified"}
