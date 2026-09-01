"""Inscription, connexion, session, réinitialisation.

Chaque point d'entrée fait trois choses dans cet ordre : valider l'origine,
ouvrir une transaction, appeler le service. Aucune logique métier ne vit ici.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from signals.accounts import service
from signals.accounts.passwords import MINIMUM_PASSWORD_LENGTH, WeakPassword
from signals.accounts.reset_delivery import DeferredDelivery
from signals.api.config import ATTRIBUTION_COOKIE_NAME, SESSION_COOKIE_NAME
from signals.api.dependencies import current_session, enforce_origin, request_now
from signals.api.errors import api_error

router = APIRouter()

Password = Annotated[str, Field(min_length=MINIMUM_PASSWORD_LENGTH, max_length=1024)]


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: Password
    company_name: str = Field(min_length=1, max_length=256)
    locale: Literal["fr", "en"] = "fr"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class PatchMeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: Literal["fr", "en"]


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class PasswordResetConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset_token: str = Field(min_length=1, max_length=512)
    new_password: Password


class InternalCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    commercial_cockpit: bool


class MeResponse(BaseModel):
    """Ce que le frontend a besoin de savoir — aucun secret n'y figure."""

    user_id: str
    email: str
    account_id: str
    account_display_name: str
    locale: str
    onboarding_status: str
    capabilities: InternalCapabilities


def _me_response(user, request: Request) -> MeResponse:
    return MeResponse(
        **vars(user),
        capabilities=InternalCapabilities(
            commercial_cockpit=(
                user.account_id in request.app.state.config.cockpit_operator_account_ids
            )
        ),
    )


def _set_session_cookie(response: Response, request: Request, session) -> None:
    config = request.app.state.config
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session.raw_token,
        max_age=int(config.session_ttl.total_seconds()),
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        path="/",
        expires=session.expires_at,
    )


@router.post("/auth/signup", status_code=201)
def signup(payload: SignupRequest, request: Request, response: Response) -> MeResponse:
    config = request.app.state.config
    enforce_origin(request, config)
    now = request_now(request)
    try:
        with request.app.state.engine.begin() as connection:
            session = service.sign_up(
                connection,
                email=payload.email,
                password=payload.password,
                company_name=payload.company_name,
                locale=payload.locale,
                now=now,
                session_ttl=config.session_ttl,
            )
            user = service.current_user(connection, user_id=session.user_id)
            attribution = getattr(
                request.app.state, "conversion_attribution_service", None
            )
            raw_attribution = request.cookies.get(ATTRIBUTION_COOKIE_NAME)
            if attribution is not None and raw_attribution:
                attribution.bind_signup_in_transaction(
                    connection,
                    account_id=session.account_id,
                    raw_token=raw_attribution,
                    at=now,
                )
    except service.EmailAlreadyUsed as error:
        # Message volontairement neutre : il ne confirme pas qu'un compte existe.
        raise api_error(409, error.code, "impossible de créer ce compte") from error
    except service.UnsupportedLocale as error:
        raise api_error(422, error.code, "langue non prise en charge") from error
    except WeakPassword as error:
        raise api_error(422, "invalid_input", str(error)) from error

    _set_session_cookie(response, request, session)
    if request.cookies.get(ATTRIBUTION_COOKIE_NAME):
        response.delete_cookie(ATTRIBUTION_COOKIE_NAME, path="/auth/signup")
    return _me_response(user, request)


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> MeResponse:
    config = request.app.state.config
    enforce_origin(request, config)
    now = request_now(request)
    try:
        with request.app.state.engine.begin() as connection:
            session = service.log_in(
                connection,
                email=payload.email,
                password=payload.password,
                now=now,
                session_ttl=config.session_ttl,
            )
            user = service.current_user(connection, user_id=session.user_id)
    except service.InvalidCredentials as error:
        raise api_error(401, error.code, "identifiants invalides") from error

    _set_session_cookie(response, request, session)
    return _me_response(user, request)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response) -> Response:
    config = request.app.state.config
    enforce_origin(request, config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        service.log_out(connection, session_id=session.session_id, now=now)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.status_code = 204
    return response


@router.get("/me")
def me(request: Request) -> MeResponse:
    now = request_now(request)
    with request.app.state.engine.connect() as connection:
        session = current_session(request, connection, now)
        user = service.current_user(connection, user_id=session.user_id)
    return _me_response(user, request)


@router.patch("/me")
def patch_me(payload: PatchMeRequest, request: Request) -> MeResponse:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        service.update_locale(
            connection,
            account_id=session.account_id,
            locale=payload.locale,
            now=now,
        )
        user = service.current_user(connection, user_id=session.user_id)
    return _me_response(user, request)


@router.post("/auth/password-reset/request", status_code=202)
def password_reset_request(
    payload: PasswordResetRequest, request: Request, background: BackgroundTasks
) -> dict[str, str]:
    """Même réponse publique, et même DURÉE, que le compte existe ou non (§11).

    L'égalité des réponses ne suffisait pas. Tant que la remise ne faisait rien,
    les deux chemins coûtaient le même temps ; dès qu'un vrai transport SMTP est
    branché, l'aller-retour n'a lieu que pour un compte existant. Mesuré sur
    staging : ~2,2 s pour une adresse connue contre ~0,1 s pour une inconnue,
    avec le MÊME corps de réponse. La durée trahissait l'existence du compte, et
    une poignée de requêtes suffisait à énumérer les clients.

    La remise est donc retenue, puis exécutée après la réponse.

    `add_task` est appelé SANS condition — voir `DeferredDelivery`. La route
    ignore s'il y a quoi que ce soit à envoyer, et c'est précisément ce qui
    garantit qu'elle ne peut pas trahir l'information : demander « ai-je un
    e-mail à envoyer ? » pour décider de programmer la tâche recréerait la
    branche observable qu'on vient de fermer.
    """
    config = request.app.state.config
    enforce_origin(request, config)
    now = request_now(request)
    deferred = DeferredDelivery(request.app.state.password_reset_delivery)
    with request.app.state.engine.begin() as connection:
        service.request_password_reset(
            connection,
            email=payload.email,
            now=now,
            reset_ttl=config.password_reset_ttl,
            delivery=deferred,
        )
    background.add_task(deferred.flush)
    return {"status": "accepted"}


@router.post("/auth/password-reset/confirm")
def password_reset_confirm(
    payload: PasswordResetConfirm, request: Request, response: Response
) -> dict[str, str]:
    config = request.app.state.config
    enforce_origin(request, config)
    now = request_now(request)
    try:
        with request.app.state.engine.begin() as connection:
            service.confirm_password_reset(
                connection,
                reset_token=payload.reset_token,
                new_password=payload.new_password,
                now=now,
            )
    except service.InvalidResetToken as error:
        raise api_error(400, error.code, "jeton de réinitialisation invalide") from error
    except WeakPassword as error:
        raise api_error(422, "invalid_input", str(error)) from error

    # Toutes les sessions ont été révoquées : le cookie courant ne vaut plus rien.
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"status": "password_updated"}
