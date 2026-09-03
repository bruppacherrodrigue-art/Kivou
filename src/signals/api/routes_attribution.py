"""Le lien du cold mail — il attribue, et il dépose le prospect sur sa promesse.

    Ce que ce lien EST, et ce qu'il n'est pas
    ─────────────────────────────────────────
    C'est un lien magique : le suivre ouvre une session sur un compte
    Découverte, sans mot de passe. Il ne le peut que parce qu'il est signé
    (HMAC), daté (expiration portée par la charge) et qu'il n'ouvre JAMAIS
    autre chose que le compte qu'il a lui-même créé — jamais un compte où
    quelqu'un s'est inscrit avec son adresse et son mot de passe.

    Pourquoi créer un compte plutôt que montrer une page publique
    ────────────────────────────────────────────────────────────
    Le mail promet UN signal. Une page publique le montrerait sans rien
    retenir : ni retour, ni note, ni alerte, ni le reste du feed. Le compte
    Découverte est ce qui transforme une promesse tenue en produit.

    L'identité du prospect n'est PAS connue
    ───────────────────────────────────────
    La chaîne d'acquisition est sans PII par construction : le jeton ne porte
    qu'une empreinte opaque de destinataire. Le compte est donc créé avec une
    identité de remplacement non délivrable (`…@landing.kivou.invalid`) et un
    mot de passe aléatoire que personne ne connaît. La vraie adresse se
    collecte à la confirmation du profil, pas ici.
"""

from __future__ import annotations

import datetime as dt
import secrets
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from signals.accounts import service as accounts
from signals.accounts.icp_input import TargetIcpInput, offer_for_need
from signals.api.config import ATTRIBUTION_COOKIE_NAME
from signals.api.dependencies import request_now
from signals.api.errors import api_error
from signals.api.routes_auth import set_session_cookie
from signals.engagement import analytics

router = APIRouter()

#: Le feed, quand la promesse n'est pas encore matérialisable pour ce compte.
FEED_PATH = "/app/signals"

#: Là où repart un lien invalide ou périmé : l'inscription ordinaire, prévenue.
EXPIRED_PATH = "/signup?attribution=expired"

#: Domaine réservé (RFC 2606) : rien n'y est délivrable, donc aucun message ne
#: partira jamais vers cette adresse par accident.
LANDING_EMAIL_DOMAIN = "landing.kivou.invalid"

#: Le nom affiché tant que le client n'a pas confirmé le sien.
LANDING_COMPANY_NAME = "Compte à confirmer"

#: L'étiquette du profil brouillon déduit du jeton.
LANDING_ICP_LABEL = "Profil à confirmer"


def _landing_email(token_fingerprint: str) -> str:
    return f"landing+{token_fingerprint[:12]}@{LANDING_EMAIL_DOMAIN}"


def _draft_icp_input(*, country: str, need_ref: str) -> TargetIcpInput:
    """Le peu que le jeton sait, et RIEN de plus.

    Le montant plancher n'est pas deviné : c'est précisément ce qui laisse le
    profil `draft`, donc muet pour le moteur (`FEEDING_ICP_STATUS = "active"`).
    Aucun signal n'est matérialisé avant que le client ait confirmé.
    """
    offer = offer_for_need(need_ref)
    return TargetIcpInput(
        offers=(offer,) if offer is not None else (),
        territories=(country,),
    )


def _redirect(url: str) -> RedirectResponse:
    response = RedirectResponse(url=url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/a/{token}", include_in_schema=False)
def attribution_click(token: str, request: Request) -> RedirectResponse:
    service = getattr(request.app.state, "conversion_attribution_service", None)
    if service is None:
        raise api_error(404, "attribution_not_found", "lien introuvable")
    config = request.app.state.config
    now = request_now(request)

    try:
        with request.app.state.engine.begin() as connection:
            landing = _land(connection, service, raw_token=token, now=now, config=config)
    except ValueError:
        # Signature fausse, jeton périmé, membre inconnu : aucune session, aucun
        # compte, et une page d'inscription qui sait pourquoi elle est là.
        return _redirect(EXPIRED_PATH)

    session, signal_key, expires_at = landing
    destination = FEED_PATH if signal_key is None else f"{FEED_PATH}/{quote(signal_key)}"
    response = _redirect(destination)
    set_session_cookie(response, request, session)
    # Le cookie d'attribution reste posé : il ne sert plus à CE compte — sa
    # journey est déjà liée — mais il garde attribuée une inscription ordinaire
    # faite ensuite depuis le même navigateur (adresse réelle, mot de passe
    # choisi), qui crée un autre compte. Le retirer perdrait cette source.
    response.set_cookie(
        ATTRIBUTION_COOKIE_NAME,
        token,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        path="/auth/signup",
        expires=expires_at,
    )
    return response


def _land(
    connection,
    service,
    *,
    raw_token: str,
    now: dt.datetime,
    config,
) -> tuple[accounts.AuthenticatedSession, str | None, dt.datetime]:
    """Tout l'atterrissage, dans UNE transaction. Rien ou tout.

    Un compte à moitié créé — sans utilisateur, sans journey, sans promesse
    enregistrée — serait un compte que personne ne peut ni ouvrir ni réclamer.
    """
    verified = service.verify_in_transaction(connection, raw_token=raw_token, at=now)
    click = service.record_click_in_transaction(connection, raw_token=raw_token, at=now)
    payload = verified.payload

    account_id = service.landed_account_in_transaction(
        connection, token_fingerprint=click.token_fingerprint
    )
    if account_id is None:
        email = _landing_email(click.token_fingerprint)
        if accounts.user_id_for_email(connection, email=email) is not None:
            # L'identité d'atterrissage existe sans ligne d'atterrissage : ce
            # compte n'a pas été créé par ce lien, et le lien n'ouvre que ce
            # qu'il a créé. On refuse plutôt que d'offrir une session.
            raise ValueError("landing identity is already used")
        session = accounts.sign_up(
            connection,
            email=email,
            # Jamais rendu, jamais journalisé : le compte s'ouvre par le lien,
            # et se réclame plus tard par une réinitialisation de mot de passe.
            password=secrets.token_urlsafe(32),
            company_name=LANDING_COMPANY_NAME,
            locale="fr",
            now=now,
            session_ttl=config.session_ttl,
        )
        account_id = session.account_id
        service.bind_signup_in_transaction(
            connection, account_id=account_id, raw_token=raw_token, at=now
        )
    else:
        user_id = accounts.active_user_id(connection, account_id=account_id)
        if user_id is None:
            raise ValueError("landing account has no active user")
        session = accounts.open_session(
            connection, user_id=user_id, now=now, session_ttl=config.session_ttl
        )

    if not accounts.list_target_icps(connection, account_id=account_id):
        accounts.create_target_icp(
            connection,
            account_id=account_id,
            label=LANDING_ICP_LABEL,
            customer_input=_draft_icp_input(
                country=payload.country, need_ref=payload.need_ref
            ),
            now=now,
        )

    signal_key: str | None = None
    if payload.opportunity_key is not None:
        signal_key = accounts.resolve_landing_signal_key(
            connection, account_id=account_id, opportunity_key=payload.opportunity_key
        )
        accounts.record_landing_signal(
            connection,
            account_id=account_id,
            opportunity_key=payload.opportunity_key,
            signal_key=signal_key,
            now=now,
        )

    analytics.record(
        connection,
        account_id=account_id,
        event_type="attribution_landed",
        occurred_at=now,
        user_id=session.user_id,
        signal_key=signal_key,
        properties={
            "has_signal": signal_key is not None,
            "replayed": click.replayed,
            "campaign_ref": payload.campaign_ref,
        },
    )
    return session, signal_key, click.expires_at


__all__ = ["router"]
