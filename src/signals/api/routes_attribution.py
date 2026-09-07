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

L'adresse reste côté serveur, liée à un identifiant opaque signé. Un compte
préexistant ou vérifié reçoit un aperçu public sans session ; seul le compte
non vérifié créé par ce jeton peut être rouvert avec la même adresse.
"""

from __future__ import annotations

import datetime as dt
import secrets
from urllib.parse import quote

import sqlalchemy as sa
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from signals.accounts import service as accounts
from signals.accounts.icp_input import MonetaryThreshold, TargetIcpInput, offer_for_need
from signals.accounts.schema import account_landing_signal, auth_user
from signals.api.config import ATTRIBUTION_COOKIE_NAME
from signals.api.dependencies import enforce_origin, request_now
from signals.api.errors import api_error
from signals.api.routes_auth import set_session_cookie
from signals.conversion import qa_token
from signals.conversion.recipient_records import resolve_recipient
from signals.conversion.token import AttributionTokenKeyring
from signals.domain.cpv_labels import cpv_label
from signals.domain.french_departments import department_label, location_subdivision
from signals.domain.prospect import require_prospect_eligible
from signals.engagement import analytics
from signals.feed.query import is_customer_display_name
from signals.ingestion.backfill import (
    materialize_landing_feed_in_transaction,
)
from signals.persistence.schema import (
    acquisition_campaign_member,
    acquisition_personalization_artifact,
    contract_award,
    for_you_sentence,
    opportunity_representation,
)
from signals.personalization.for_you import ForYouInput, client_safe_sentence, fallback_sentence
from signals.supplier_discovery.seed import (
    AcquisitionSeedNotFound,
    resolve_public_acquisition_context_in_transaction,
)

router = APIRouter()

#: Le feed, quand la promesse n'est pas encore matérialisable pour ce compte.
FEED_PATH = "/app/signals"

#: Là où repart un lien invalide ou périmé : l'inscription ordinaire, prévenue.
EXPIRED_PATH = "/signup?attribution=expired"

#: Le nom affiché tant que le client n'a pas confirmé le sien.
LANDING_COMPANY_NAME = "Compte à confirmer"

#: L'étiquette du profil brouillon déduit du jeton.
LANDING_ICP_LABEL = "Profil à confirmer"

PROVISIONAL_OFFERS = (
    "materials_and_components",
    "equipment_rental",
    "staffing_and_labour",
    "transport_and_logistics",
    "specialist_subcontracting",
    "safety_equipment",
    "waste_and_environmental_services",
)


def _draft_icp_input(
    *,
    country: str,
    need_ref: str,
    sector_label: str | None,
    cpv_prefix: str | None,
    subdivision: str | None,
) -> TargetIcpInput:
    """Profil provisoire fondé seulement sur le signal effectivement promis."""
    offer = offer_for_need(need_ref)
    return TargetIcpInput(
        offer_summary=sector_label or need_ref.replace("_", " ").lower(),
        # Une ancienne taxonomie de campagne peut ne pas avoir de traduction
        # directe. Le profil reste signalé comme provisoire : élargir ici sert
        # uniquement à matérialiser la promesse, jamais à confirmer un choix.
        offers=(offer,) if offer is not None else PROVISIONAL_OFFERS,
        territories=(country,),
        territory_subdivisions=(subdivision,) if subdivision else (),
        sector_cpv_prefixes=(cpv_prefix,) if cpv_prefix else (),
        minimum_contract_value=MonetaryThreshold(
            currency="CHF" if country == "CH" else "EUR",
            minimum_amount=0,
        ),
    )


def _profile_seed(
    connection, opportunity_key: str | None
) -> tuple[str | None, str | None, str | None]:
    if opportunity_key is None:
        return None, None, None
    row = connection.execute(
        sa.select(contract_award.c.cpv_main, contract_award.c.place_of_performance)
        .select_from(
            opportunity_representation.join(
                contract_award,
                opportunity_representation.c.award_key == contract_award.c.award_key,
            )
        )
        .where(opportunity_representation.c.opportunity_key == opportunity_key)
        .order_by(contract_award.c.award_key)
        .limit(1)
    ).first()
    if row is None:
        return None, None, None
    code, place = row
    prefix = code[:2] if code and len(code) >= 2 else None
    return cpv_label(code, lang="fr"), prefix, location_subdivision(place)


def _redirect(url: str) -> RedirectResponse:
    response = RedirectResponse(url=url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _mail_for_you_sentence(connection, *, member_ref: str) -> str | None:
    snapshot = connection.scalar(
        sa.select(acquisition_personalization_artifact.c.input_snapshot)
        .select_from(
            acquisition_campaign_member.join(
                acquisition_personalization_artifact,
                acquisition_campaign_member.c.personalization_artifact_id
                == acquisition_personalization_artifact.c.personalization_artifact_id,
            )
        )
        .where(acquisition_campaign_member.c.member_ref == member_ref)
    )
    return snapshot.get("for_you_sentence") if isinstance(snapshot, dict) else None


def _verify_addressed_token(connection, service, *, raw_token, now, config, lock=False):
    is_qa = raw_token.startswith("kqa1.")
    if is_qa:
        if not config.attribution_hmac_key or not config.attribution_hmac_key_version:
            raise ValueError("QA attribution key is unavailable")
        keyring = AttributionTokenKeyring(
            current_key_version=config.attribution_hmac_key_version,
            keys={config.attribution_hmac_key_version: config.attribution_hmac_key},
        )
        payload = qa_token.verify(raw_token, keyring=keyring, at=now)
        fingerprint = qa_token.fingerprint(raw_token)
        recipient_key = payload.nonce
    else:
        if service is None:
            raise ValueError("Attribution service unavailable")
        verified = service.verify_in_transaction(connection, raw_token=raw_token, at=now)
        payload, fingerprint = verified.payload, verified.token_fingerprint
        recipient_key = fingerprint
    email = resolve_recipient(connection, nonce=recipient_key, now=now, lock=lock)
    return payload, fingerprint, email, is_qa


def _landing_identity(connection, *, fingerprint, email, lock=False):
    """Return only the identity created by this token, rejecting address drift."""
    account_id = connection.scalar(sa.select(account_landing_signal.c.account_id).where(
        account_landing_signal.c.token_fingerprint == fingerprint,
    ))
    if account_id is None:
        return None, None
    query = sa.select(auth_user.c.user_id, auth_user.c.email_normalized).where(
        auth_user.c.account_id == account_id, auth_user.c.is_active.is_(True),
    )
    if lock:
        query = query.with_for_update()
    user = connection.execute(query).one_or_none()
    if user is None or accounts.normalize_email(user.email_normalized) != email:
        raise ValueError("Attribution identity changed or deactivated")
    return account_id, user.user_id


def _requires_public_preview(connection, *, user_id, email):
    if user_id is None:
        return accounts.user_id_for_email(connection, email=email) is not None
    from signals.accounts.email_verification import is_user_verified

    return is_user_verified(connection, user_id=user_id)


def _public_context(connection, payload, *, now):
    if not payload.opportunity_key:
        raise ValueError("Attribution opportunity unavailable")
    public = resolve_public_acquisition_context_in_transaction(connection, payload.opportunity_key)
    require_prospect_eligible(public.award, public.event, as_of=now.date())
    place = public.award.place_of_performance
    if place is None or place.country != payload.country:
        raise ValueError("Attribution opportunity unavailable in the requested country")
    return public


def _public_signal(connection, *, public, payload, fingerprint, is_qa):
    award, event = public.award, public.event
    title = (award.lot.title if award.lot else None) or award.title
    if not title or not title.strip(" \t\n—-"):
        title = cpv_label(award.cpv_main.code, lang="fr") if award.cpv_main else None

    def published_name(organizations):
        return next((organization.legal_name for organization in organizations
                     if is_customer_display_name(
                         organization.legal_name,
                         organization.identifiers[0].value if organization.identifiers else None,
                     )), None)

    holder = published_name(award.awardee_organizations())
    buyer = published_name(event.procedure_buyers)
    place = award.place_of_performance
    location = (place.locality or department_label(location_subdivision(
        place.model_dump(mode="json"))) or place.country) if place else None
    attribution_date = award.award_date or award.contract_notification_date
    date = attribution_date or event.published_at
    if isinstance(date, dt.datetime):
        date = date.date()
    amount = str(award.value.amount) if award.value else None
    currency = award.value.currency if award.value else None
    sentence = None if is_qa else _mail_for_you_sentence(
        connection, member_ref=payload.member_ref,
    )
    if not client_safe_sentence(sentence):
        sentence = connection.scalar(
            sa.select(for_you_sentence.c.sentence)
            .join(account_landing_signal,
                  account_landing_signal.c.signal_key == for_you_sentence.c.signal_key)
            .where(account_landing_signal.c.token_fingerprint == fingerprint)
            .order_by(for_you_sentence.c.created_at.desc()).limit(1)
        )
    sentence = client_safe_sentence(sentence) or fallback_sentence(ForYouInput(
        holder=holder, buyer_name=buyer, title=title,
        amount=f"{amount} {currency}" if amount is not None else None,
        location=location, awarded_on=date.isoformat() if date else None,
    ))
    return {
        "object": title, "holder": holder, "buyer": buyer, "amount": amount,
        "currency": currency, "location": location, "date": date.isoformat() if date else None,
        "date_label": "Attribué le" if attribution_date else "Publié le",
        "for_you_sentence": sentence,
    }


class AttributionPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=4096)


@router.post("/auth/attribution/preview")
def attribution_preview(body: AttributionPreviewInput, request: Request) -> JSONResponse:
    config = request.app.state.config
    enforce_origin(request, config)
    now = request_now(request)
    service = getattr(request.app.state, "conversion_attribution_service", None)
    try:
        with request.app.state.engine.connect() as connection:
            payload, fingerprint, email, is_qa = _verify_addressed_token(
                connection, service, raw_token=body.token, now=now, config=config,
            )
            _landing_identity(connection, fingerprint=fingerprint, email=email)
            public = _public_context(connection, payload, now=now)
            signal = _public_signal(
                connection, public=public, payload=payload,
                fingerprint=fingerprint, is_qa=is_qa,
            )
    except (ValueError, AcquisitionSeedNotFound):
        raise api_error(400, "attribution_not_found", "lien invalide ou expiré") from None
    return JSONResponse(
        {"recipient_email": email, "signal": signal},
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.get("/a/{token}", include_in_schema=False)
def attribution_click(token: str, request: Request) -> RedirectResponse:
    service = getattr(request.app.state, "conversion_attribution_service", None)
    if service is None:
        raise api_error(404, "attribution_not_found", "lien introuvable")
    config = request.app.state.config
    now = request_now(request)

    try:
        with request.app.state.engine.begin() as connection:
            land = _land_qa if token.startswith("kqa1.") else _land
            landing = land(connection, service, raw_token=token, now=now, config=config)
    except (ValueError, AcquisitionSeedNotFound):
        # Signature fausse, jeton périmé, membre inconnu : aucune session, aucun
        # compte, et une page d'inscription qui sait pourquoi elle est là.
        return _redirect(EXPIRED_PATH)

    session, signal_key, expires_at = landing
    if session is None:
        return _redirect(f"/public-signal#{token}")
    destination = FEED_PATH if signal_key is None else f"{FEED_PATH}/{quote(signal_key)}"
    response = _redirect(destination)
    set_session_cookie(response, request, session)
    if token.startswith("kqa1."):
        # QA must not inherit or create a commercial signup-attribution cookie.
        response.delete_cookie(ATTRIBUTION_COOKIE_NAME, path="/auth/signup",
                               secure=config.cookie_secure, httponly=True, samesite="lax")
        return response
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
    payload, fingerprint, email, _ = _verify_addressed_token(
        connection, service, raw_token=raw_token, now=now, config=config, lock=True,
    )
    _public_context(connection, payload, now=now)
    account_id, user_id = _landing_identity(
        connection, fingerprint=fingerprint, email=email, lock=True,
    )
    if _requires_public_preview(connection, user_id=user_id, email=email):
        return None, None, payload.expires_at
    click = service.record_click_in_transaction(connection, raw_token=raw_token, at=now)
    if account_id is None:
        session = accounts.sign_up(
            connection,
            email=email,
            # Jamais rendu, jamais journalisé : le compte s'ouvre par le lien,
            # et se réclame plus tard par une réinitialisation de mot de passe.
            password=secrets.token_urlsafe(32),
            company_name=LANDING_COMPANY_NAME,
            locale="fr",
            now=now,
            session_ttl=min(config.session_ttl, payload.expires_at - now),
        )
        account_id = session.account_id
        service.bind_signup_in_transaction(
            connection, account_id=account_id, raw_token=raw_token, at=now
        )
    else:
        session = accounts.open_session(
            connection, user_id=user_id, now=now,
            session_ttl=min(config.session_ttl, payload.expires_at - now),
        )

    if not accounts.list_target_icps(connection, account_id=account_id):
        sector_label, cpv_prefix, subdivision = _profile_seed(connection, payload.opportunity_key)
        provisional = accounts.create_target_icp(
            connection,
            account_id=account_id,
            label=sector_label or LANDING_ICP_LABEL,
            customer_input=_draft_icp_input(
                country=payload.country,
                need_ref=payload.need_ref,
                sector_label=sector_label,
                cpv_prefix=cpv_prefix,
                subdivision=subdivision,
            ),
            now=now,
        )
        if payload.opportunity_key is not None:
            materialize_landing_feed_in_transaction(
                connection,
                target_icp_id=provisional.target_icp_id,
                opportunity_key=payload.opportunity_key,
                as_of=now.date(),
                materialized_at=now,
            )
        accounts.mark_provisional_onboarding(connection, account_id=account_id, now=now)

    # Écrite pour CHAQUE atterrissage, opportunité résolue ou non : c'est cette
    # ligne — pas `opportunity_key` — que `landed_account_in_transaction`
    # utilise pour reconnaître un rejeu du même jeton. Ne l'écrire que dans le
    # cas résolu ferait manquer cette reconnaissance sur un jeton par ailleurs
    # parfaitement valide, et le rejeu retomberait sur le garde-fou d'identité
    # déjà utilisée (revue PR2b tâche 5).
    signal_key: str | None = None
    if payload.opportunity_key is not None:
        signal_key = accounts.resolve_landing_signal_key(
            connection, account_id=account_id, opportunity_key=payload.opportunity_key
        )
    mail_sentence = _mail_for_you_sentence(connection, member_ref=payload.member_ref)
    if signal_key is not None and mail_sentence:
        # Le mail est déjà parti : sa phrase devient la valeur figée de cette
        # paire afin que le drawer ne raconte jamais autre chose ensuite.
        connection.execute(
            sa.update(for_you_sentence)
            .where(for_you_sentence.c.signal_key == signal_key)
            .values(
                sentence=mail_sentence,
                fallback_sentence=mail_sentence,
                provenance="fallback",
                state="completed",
                validation_reason=None,
                validation_detail=None,
                updated_at=now,
                completed_at=now,
            )
        )
    accounts.record_landing_signal(
        connection,
        account_id=account_id,
        opportunity_key=payload.opportunity_key,
        signal_key=signal_key,
        token_fingerprint=click.token_fingerprint,
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


def _land_qa(connection, service, *, raw_token: str, now: dt.datetime, config):
    payload, fingerprint, email, _ = _verify_addressed_token(
        connection, service, raw_token=raw_token, now=now, config=config, lock=True,
    )
    _public_context(connection, payload, now=now)
    account_id, user_id = _landing_identity(
        connection, fingerprint=fingerprint, email=email, lock=True,
    )
    if _requires_public_preview(connection, user_id=user_id, email=email):
        return None, None, payload.expires_at
    replayed = account_id is not None
    if account_id is None:
        _, cpv_prefix, subdivision = _profile_seed(connection, payload.opportunity_key)
        available = connection.scalar(sa.select(sa.exists().where(
            opportunity_representation.c.opportunity_key == payload.opportunity_key,
            opportunity_representation.c.award_key == contract_award.c.award_key,
            contract_award.c.place_country == payload.country,
        )))
        if not available:
            raise ValueError("QA opportunity unavailable")
        session = accounts.sign_up(
            connection, email=email, password=secrets.token_urlsafe(48),
            company_name="Compte de recette", locale="fr", now=now,
            session_ttl=min(config.session_ttl, payload.expires_at - now),
        )
        account_id = session.account_id
        accounts.record_landing_signal(
            connection, account_id=account_id, opportunity_key=payload.opportunity_key,
            signal_key=None, token_fingerprint=fingerprint, qa=True, now=now,
        )
        zone = department_label(subdivision)
        label = f"{payload.sector} · {zone}" if zone else payload.sector
        provisional = accounts.create_target_icp(
            connection, account_id=account_id, label=label,
            customer_input=_draft_icp_input(
                country=payload.country, need_ref=payload.need, sector_label=payload.sector,
                cpv_prefix=cpv_prefix, subdivision=subdivision,
            ), now=now,
        )
        materialize_landing_feed_in_transaction(
            connection, target_icp_id=provisional.target_icp_id,
            opportunity_key=payload.opportunity_key, as_of=now.date(), materialized_at=now,
        )
        accounts.mark_provisional_onboarding(connection, account_id=account_id, now=now)
    else:
        session = accounts.open_session(
            connection, user_id=user_id, now=now,
            session_ttl=min(config.session_ttl, payload.expires_at - now),
        )
    signal_key = accounts.resolve_landing_signal_key(
        connection, account_id=account_id, opportunity_key=payload.opportunity_key,
    )
    if signal_key is None:
        raise ValueError("QA opportunity could not be materialized")
    accounts.record_landing_signal(
        connection, account_id=account_id, opportunity_key=payload.opportunity_key,
        signal_key=signal_key, token_fingerprint=fingerprint, qa=True, now=now,
    )
    analytics.record(
        connection, account_id=account_id, event_type="attribution_landed", occurred_at=now,
        user_id=session.user_id, signal_key=signal_key,
        properties={"qa": True, "has_signal": True, "replayed": replayed,
                    "wedge": payload.wedge, "sector": payload.sector, "need": payload.need},
    )
    return session, signal_key, payload.expires_at


__all__ = ["router"]
