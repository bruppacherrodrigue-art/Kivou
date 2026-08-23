"""Le service de comptes — inscription, session, réinitialisation, ICP client.

Aucune connaissance de HTTP ici : pas de requête, pas de cookie, pas de code de
statut. Le service reçoit des valeurs et une connexion, et rend des objets. Ce
qui le rend testable sans serveur, et réutilisable par un futur travail
planifié.

    Le temps est toujours explicite
    ───────────────────────────────
    Chaque fonction qui en dépend reçoit `now`. C'est la discipline établie par
    la politique de fraîcheur : une horloge lue en douce rend un test vert
    aujourd'hui et faux demain, et rend surtout indémontrable qu'une session
    expire vraiment.

    Ce qui ne fuit jamais
    ─────────────────────
    Une adresse inconnue et un mot de passe faux produisent la **même** réponse.
    Une demande de réinitialisation produit la même réponse qu'il existe un
    compte ou non. Sans quoi le formulaire de connexion devient un annuaire.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import secrets
from typing import Any, Protocol

import sqlalchemy as sa

from signals.accounts.icp_input import TargetIcpInput, to_target_icp
from signals.accounts.passwords import hash_password, needs_rehash, verify_password
from signals.accounts.schema import (
    SUPPORTED_LOCALES,
    account,
    auth_session,
    auth_user,
    password_reset,
    target_icp,
)
from signals.accounts.tokens import new_token, token_hash


class AccountError(RuntimeError):
    """Erreur métier portant un code stable, destiné à l'API."""

    code = "account_error"


class EmailAlreadyUsed(AccountError):
    code = "email_already_used"


class InvalidCredentials(AccountError):
    code = "invalid_credentials"


class UnsupportedLocale(AccountError):
    code = "unsupported_locale"


class InvalidResetToken(AccountError):
    code = "invalid_reset_token"


class TargetIcpNotFound(AccountError):
    """Volontairement indistinct d'un ICP appartenant à un autre compte (§13)."""

    code = "target_icp_not_found"


class TerritoryLimitExceeded(AccountError):
    code = "territory_limit_exceeded"

    def __init__(self, *, limit: int, territory_count: int) -> None:
        super().__init__(f"{territory_count} territoires pour une limite de {limit}")
        self.limit = limit
        self.territory_count = territory_count


class PasswordResetDelivery(Protocol):
    """La frontière par où sortira un jour un e-mail transactionnel.

    Elle reçoit le jeton **en clair** — c'est le seul endroit du système qui le
    voit après sa génération. Aucune implémentation n'est fournie ici : SPEC-011
    n'intègre aucun fournisseur d'envoi.
    """

    def deliver(self, *, email: str, locale: str, reset_token: str) -> None: ...


@dataclasses.dataclass(frozen=True)
class AuthenticatedSession:
    """Une session ouverte. `raw_token` n'existe qu'en mémoire, jamais en base."""

    session_id: str
    user_id: str
    account_id: str
    raw_token: str
    expires_at: dt.datetime


@dataclasses.dataclass(frozen=True)
class CurrentUser:
    """Ce que `/me` a le droit de rendre — aucun secret n'y figure."""

    user_id: str
    email: str
    account_id: str
    account_display_name: str
    locale: str
    onboarding_status: str


def normalize_email(email: str) -> str:
    """Casse et espaces retirés. Une adresse, une identité.

    Aucune normalisation propre à un fournisseur — retirer les points d'une
    adresse Gmail, par exemple — parce qu'elle serait fausse pour tous les
    autres domaines et transformerait deux personnes en une.
    """
    return email.strip().casefold()


def _identifier(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(16)}"


# ─── inscription ──────────────────────────────────────────────────────────────


def sign_up(
    connection: sa.Connection,
    *,
    email: str,
    password: str,
    company_name: str,
    locale: str,
    now: dt.datetime,
    session_ttl: dt.timedelta,
) -> AuthenticatedSession:
    """Crée un compte, son propriétaire et une session — tout ou rien.

    L'écriture se fait dans la transaction de l'appelant. Un échec à mi-chemin
    ne laisse donc ni compte orphelin ni utilisateur sans compte : c'est la base
    qui l'interdit, pas une séquence de nettoyage.
    """
    if locale not in SUPPORTED_LOCALES:
        raise UnsupportedLocale(f"locale non prise en charge : {locale}")

    normalized = normalize_email(email)
    existing = connection.execute(
        sa.select(auth_user.c.user_id).where(auth_user.c.email_normalized == normalized)
    ).scalar_one_or_none()
    if existing is not None:
        raise EmailAlreadyUsed("adresse déjà utilisée")

    account_id = _identifier("acc")
    user_id = _identifier("usr")
    connection.execute(
        sa.insert(account).values(
            account_id=account_id,
            display_name=company_name.strip(),
            locale=locale,
            onboarding_status="account_created",
            created_at=now,
            updated_at=now,
        )
    )
    connection.execute(
        sa.insert(auth_user).values(
            user_id=user_id,
            account_id=account_id,
            email_normalized=normalized,
            password_hash=hash_password(password),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )
    return open_session(connection, user_id=user_id, now=now, session_ttl=session_ttl)


# ─── sessions ─────────────────────────────────────────────────────────────────


def open_session(
    connection: sa.Connection, *, user_id: str, now: dt.datetime, session_ttl: dt.timedelta
) -> AuthenticatedSession:
    """Ouvre une session et rend le jeton en clair — la seule fois où il existe."""
    account_id = connection.execute(
        sa.select(auth_user.c.account_id).where(auth_user.c.user_id == user_id)
    ).scalar_one()
    raw = new_token()
    session_id = _identifier("ses")
    expires_at = now + session_ttl
    connection.execute(
        sa.insert(auth_session).values(
            session_id=session_id,
            user_id=user_id,
            token_hash=token_hash(raw),
            created_at=now,
            expires_at=expires_at,
            last_seen_at=now,
        )
    )
    return AuthenticatedSession(session_id, user_id, account_id, raw, expires_at)


def log_in(
    connection: sa.Connection,
    *,
    email: str,
    password: str,
    now: dt.datetime,
    session_ttl: dt.timedelta,
) -> AuthenticatedSession:
    """Authentifie, ou lève la MÊME erreur quelle que soit la cause.

    Adresse inconnue, mot de passe faux, compte désactivé : une seule réponse.
    Distinguer les trois transformerait le formulaire en annuaire d'abonnés.
    """
    normalized = normalize_email(email)
    row = connection.execute(
        sa.select(auth_user.c.user_id, auth_user.c.password_hash, auth_user.c.is_active).where(
            auth_user.c.email_normalized == normalized
        )
    ).one_or_none()

    if row is None:
        # Vérification à vide : le temps de réponse ne doit pas révéler
        # l'absence de compte.
        verify_password("$argon2id$v=19$m=65536,t=3,p=4$" + "A" * 22 + "$" + "B" * 43, password)
        raise InvalidCredentials("identifiants invalides")

    user_id, password_hash, is_active = row
    if not verify_password(password_hash, password) or not is_active:
        raise InvalidCredentials("identifiants invalides")

    # Closeout §4 — la connexion réussie est le SEUL instant où le mot de passe
    # en clair est disponible : c'est donc le seul moment où l'empreinte peut
    # être remise aux paramètres courants. Elle est réécrite dans la même
    # transaction que la connexion, jamais pour un utilisateur inconnu, un mot
    # de passe faux ou une empreinte illisible — les trois ont déjà été
    # renvoyés plus haut.
    values: dict[str, Any] = {"last_login_at": now, "updated_at": now}
    if needs_rehash(password_hash):
        values["password_hash"] = hash_password(password)

    connection.execute(sa.update(auth_user).where(auth_user.c.user_id == user_id).values(**values))
    return open_session(connection, user_id=user_id, now=now, session_ttl=session_ttl)


def authenticate(
    connection: sa.Connection, *, raw_token: str, now: dt.datetime
) -> AuthenticatedSession | None:
    """La session portée par ce jeton, si elle est vivante. `None` sinon.

    Inconnue, expirée, révoquée : trois raisons, une seule réponse. L'appelant
    n'a pas besoin de savoir laquelle, et le client encore moins.
    """
    row = connection.execute(
        sa.select(
            auth_session.c.session_id,
            auth_session.c.user_id,
            auth_session.c.expires_at,
            auth_session.c.revoked_at,
            auth_user.c.account_id,
            auth_user.c.is_active,
        )
        .select_from(auth_session.join(auth_user, auth_session.c.user_id == auth_user.c.user_id))
        .where(auth_session.c.token_hash == token_hash(raw_token))
    ).one_or_none()
    if row is None:
        return None

    session_id, user_id, expires_at, revoked_at, account_id, is_active = row
    if revoked_at is not None or not is_active:
        return None
    if _aware(expires_at) <= now:
        return None

    connection.execute(
        sa.update(auth_session)
        .where(auth_session.c.session_id == session_id)
        .values(last_seen_at=now)
    )
    return AuthenticatedSession(session_id, user_id, account_id, raw_token, _aware(expires_at))


def log_out(connection: sa.Connection, *, session_id: str, now: dt.datetime) -> None:
    """Révoque la session côté serveur. Le cookie seul ne prouverait rien."""
    connection.execute(
        sa.update(auth_session)
        .where(auth_session.c.session_id == session_id, auth_session.c.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def revoke_all_sessions(connection: sa.Connection, *, user_id: str, now: dt.datetime) -> int:
    result = connection.execute(
        sa.update(auth_session)
        .where(auth_session.c.user_id == user_id, auth_session.c.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return result.rowcount


def _aware(value: Any) -> dt.datetime:
    """SQLite rend des instants nus ; tout ce qui est écrit ici est en UTC."""
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


# ─── réinitialisation de mot de passe ─────────────────────────────────────────


def request_password_reset(
    connection: sa.Connection,
    *,
    email: str,
    now: dt.datetime,
    reset_ttl: dt.timedelta,
    delivery: PasswordResetDelivery,
) -> None:
    """Émet un jeton si le compte existe — et ne dit jamais s'il existe.

    L'appelant n'apprend rien : la fonction ne rend rien et ne lève rien. Le
    jeton en clair ne sort que par `delivery`, qui deviendra un e-mail.
    """
    normalized = normalize_email(email)
    row = connection.execute(
        sa.select(auth_user.c.user_id, account.c.locale)
        .select_from(auth_user.join(account, auth_user.c.account_id == account.c.account_id))
        .where(auth_user.c.email_normalized == normalized, auth_user.c.is_active.is_(True))
    ).one_or_none()
    if row is None:
        return

    user_id, locale = row
    raw = new_token()
    # Une nouvelle demande remplace toutes les précédentes. Si un premier
    # e-mail n'est pas parti, l'utilisateur peut redemander sans laisser un
    # ancien jeton latent devenir utilisable plus tard. `used_at` conserve
    # l'historique sans stocker le jeton en clair ni supprimer de ligne.
    connection.execute(
        sa.update(password_reset)
        .where(
            password_reset.c.user_id == user_id,
            password_reset.c.used_at.is_(None),
        )
        .values(used_at=now)
    )
    connection.execute(
        sa.insert(password_reset).values(
            reset_id=_identifier("rst"),
            user_id=user_id,
            token_hash=token_hash(raw),
            created_at=now,
            expires_at=now + reset_ttl,
        )
    )
    delivery.deliver(email=normalized, locale=locale, reset_token=raw)


def confirm_password_reset(
    connection: sa.Connection, *, reset_token: str, new_password: str, now: dt.datetime
) -> str:
    """Change le mot de passe et coupe toutes les sessions ouvertes.

    Une réinitialisation sert précisément quand on soupçonne un accès
    illégitime : laisser vivre les sessions existantes annulerait l'opération.
    """
    row = connection.execute(
        sa.select(
            password_reset.c.reset_id,
            password_reset.c.user_id,
            password_reset.c.expires_at,
            password_reset.c.used_at,
        ).where(password_reset.c.token_hash == token_hash(reset_token))
    ).one_or_none()
    if row is None:
        raise InvalidResetToken("jeton de réinitialisation invalide")

    reset_id, user_id, expires_at, used_at = row
    if used_at is not None or _aware(expires_at) <= now:
        raise InvalidResetToken("jeton de réinitialisation invalide")

    connection.execute(
        sa.update(auth_user)
        .where(auth_user.c.user_id == user_id)
        .values(password_hash=hash_password(new_password), updated_at=now)
    )
    connection.execute(
        sa.update(password_reset).where(password_reset.c.reset_id == reset_id).values(used_at=now)
    )
    revoke_all_sessions(connection, user_id=user_id, now=now)
    return user_id


# ─── utilisateur courant et onboarding ────────────────────────────────────────


def current_user(connection: sa.Connection, *, user_id: str) -> CurrentUser:
    row = connection.execute(
        sa.select(
            auth_user.c.user_id,
            auth_user.c.email_normalized,
            account.c.account_id,
            account.c.display_name,
            account.c.locale,
            account.c.onboarding_status,
        )
        .select_from(auth_user.join(account, auth_user.c.account_id == account.c.account_id))
        .where(auth_user.c.user_id == user_id)
    ).one()
    return CurrentUser(*row)


def onboarding_status(connection: sa.Connection, *, account_id: str) -> str:
    """§14 — trois états déterministes, calculés, jamais stockés à la main.

    `ready_for_signals` est une complétude **technique** : le compte existe et
    au moins un profil de ciblage est exploitable par le moteur. Elle ne dit
    rien d'un paiement, d'une activation commerciale ni de signaux déjà produits.
    """
    active = connection.execute(
        sa.select(sa.func.count())
        .select_from(target_icp)
        .where(target_icp.c.account_id == account_id, target_icp.c.status == "active")
    ).scalar_one()
    if active:
        return "ready_for_signals"
    any_icp = connection.execute(
        sa.select(sa.func.count())
        .select_from(target_icp)
        .where(target_icp.c.account_id == account_id)
    ).scalar_one()
    return "icp_incomplete" if any_icp else "account_created"


def _refresh_onboarding(connection: sa.Connection, *, account_id: str, now: dt.datetime) -> str:
    status = onboarding_status(connection, account_id=account_id)
    connection.execute(
        sa.update(account)
        .where(account.c.account_id == account_id)
        .values(onboarding_status=status, updated_at=now)
    )
    return status


# ─── ICP client ───────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class StoredTargetIcp:
    """Un profil de ciblage tel que son propriétaire le voit."""

    target_icp_id: str
    account_id: str
    label: str
    status: str
    matching_revision: int
    plan_limit_code: str | None
    plan_limited_at: dt.datetime | None
    customer_input: TargetIcpInput
    missing_fields: tuple[str, ...]
    created_at: dt.datetime
    updated_at: dt.datetime


def _status_of(customer_input: TargetIcpInput, *, target_icp_id: str, label: str) -> str:
    """`active` seulement si l'entrée produit vraiment un profil moteur valide.

    La traduction est tentée pour de bon : une entrée qui satisfait les champs
    obligatoires mais que le moteur refuserait ne doit pas être annoncée prête.
    """
    if not customer_input.is_complete:
        return "draft"
    try:
        to_target_icp(customer_input, target_icp_id=target_icp_id, label=label)
    except (ValueError, TypeError):
        return "draft"
    return "active"


def _matching_criteria(customer_input: TargetIcpInput) -> tuple[Any, ...]:
    """La partie de l'entrée qui influence réellement `MatchingEngine`.

    La description libre est explicitement inerte et l'ordre de cases cochées
    ne change pas la sémantique du profil.
    """
    threshold = customer_input.minimum_contract_value
    return (
        tuple(sorted(set(customer_input.offers))),
        tuple(sorted(set(customer_input.secondary_offers))),
        tuple(sorted(set(customer_input.buyer_trades))),
        tuple(sorted(set(customer_input.secondary_buyer_trades))),
        tuple(sorted(set(customer_input.territories))),
        None
        if threshold is None
        else (threshold.currency, threshold.minimum_amount, threshold.maximum_amount),
    )


def enforce_territory_limit(customer_input: TargetIcpInput, *, max_territories: int | None) -> None:
    """Refuse une saisie trop large ; ne la tronque jamais."""
    if max_territories is None:
        return
    territory_count = len(set(customer_input.territories))
    if territory_count > max_territories:
        raise TerritoryLimitExceeded(
            limit=max_territories,
            territory_count=territory_count,
        )


def reconcile_territory_plan_limits(
    connection: sa.Connection,
    *,
    account_id: str,
    max_territories: int | None,
    now: dt.datetime,
) -> tuple[str, ...]:
    """Marque les profils rendus inutilisables par le plan sans toucher à leur saisie."""
    rows = connection.execute(
        sa.select(
            target_icp.c.target_icp_id,
            target_icp.c.status,
            target_icp.c.customer_input,
            target_icp.c.plan_limit_code,
        ).where(target_icp.c.account_id == account_id)
    ).all()
    limited: list[str] = []
    for row in rows:
        customer_input = TargetIcpInput.model_validate(row.customer_input)
        exceeds = (
            row.status == "active"
            and max_territories is not None
            and len(set(customer_input.territories)) > max_territories
        )
        code = "territory_limit_exceeded" if exceeds else None
        if exceeds:
            limited.append(row.target_icp_id)
        if row.plan_limit_code == code:
            continue
        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == row.target_icp_id)
            .values(
                plan_limit_code=code,
                plan_limited_at=now if code is not None else None,
                updated_at=now,
            )
        )
    return tuple(limited)


def create_target_icp(
    connection: sa.Connection,
    *,
    account_id: str,
    label: str,
    customer_input: TargetIcpInput,
    now: dt.datetime,
) -> StoredTargetIcp:
    """Crée un profil pour CE compte. Deux comptes n'en partagent jamais un.

    Aucune déduplication par contenu : deux clients peuvent viser exactement la
    même chose et doivent recevoir deux profils distincts, sans quoi les signaux
    de l'un apparaîtraient chez l'autre.
    """
    target_icp_id = _identifier("ticp")
    status = _status_of(customer_input, target_icp_id=target_icp_id, label=label)
    connection.execute(
        sa.insert(target_icp).values(
            target_icp_id=target_icp_id,
            account_id=account_id,
            label=label.strip(),
            status=status,
            matching_revision=1,
            plan_limit_code=None,
            plan_limited_at=None,
            customer_input=customer_input.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )
    )
    _refresh_onboarding(connection, account_id=account_id, now=now)
    return _stored(
        target_icp_id,
        account_id,
        label.strip(),
        status,
        1,
        None,
        None,
        customer_input,
        now,
        now,
    )


def get_target_icp(
    connection: sa.Connection, *, account_id: str, target_icp_id: str
) -> StoredTargetIcp:
    """Le profil, s'il appartient à CE compte. Sinon : introuvable.

    La propriété est toujours dans la clause `WHERE`. Un profil d'un autre
    compte est donc indistinguable d'un profil inexistant — ce qui interdit de
    sonder l'existence d'une ressource voisine.
    """
    row = connection.execute(
        sa.select(target_icp).where(
            target_icp.c.target_icp_id == target_icp_id,
            target_icp.c.account_id == account_id,
        )
    ).one_or_none()
    if row is None:
        raise TargetIcpNotFound("profil de ciblage introuvable")
    return _row_to_stored(row)


def list_target_icps(connection: sa.Connection, *, account_id: str) -> list[StoredTargetIcp]:
    rows = connection.execute(
        sa.select(target_icp)
        .where(target_icp.c.account_id == account_id)
        .order_by(target_icp.c.created_at, target_icp.c.target_icp_id)
    ).all()
    return [_row_to_stored(row) for row in rows]


def update_target_icp(
    connection: sa.Connection,
    *,
    account_id: str,
    target_icp_id: str,
    label: str | None,
    customer_input: TargetIcpInput | None,
    now: dt.datetime,
) -> StoredTargetIcp:
    """Complète ou corrige un profil. Le statut est recalculé, jamais imposé."""
    row = connection.execute(
        sa.select(target_icp)
        .where(
            target_icp.c.target_icp_id == target_icp_id,
            target_icp.c.account_id == account_id,
        )
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise TargetIcpNotFound("profil de ciblage introuvable")
    existing = _row_to_stored(row)
    new_label = (label or existing.label).strip()
    new_input = customer_input if customer_input is not None else existing.customer_input
    status = _status_of(new_input, target_icp_id=target_icp_id, label=new_label)
    criteria_changed = _matching_criteria(new_input) != _matching_criteria(existing.customer_input)
    matching_revision = existing.matching_revision + int(criteria_changed)
    connection.execute(
        sa.update(target_icp)
        .where(
            target_icp.c.target_icp_id == target_icp_id,
            target_icp.c.account_id == account_id,
        )
        .values(
            label=new_label,
            status=status,
            matching_revision=matching_revision,
            customer_input=new_input.model_dump(mode="json"),
            updated_at=now,
        )
    )
    _refresh_onboarding(connection, account_id=account_id, now=now)
    return _stored(
        target_icp_id,
        account_id,
        new_label,
        status,
        matching_revision,
        existing.plan_limit_code,
        existing.plan_limited_at,
        new_input,
        existing.created_at,
        now,
    )


def _stored(
    target_icp_id: str,
    account_id: str,
    label: str,
    status: str,
    matching_revision: int,
    plan_limit_code: str | None,
    plan_limited_at: dt.datetime | None,
    customer_input: TargetIcpInput,
    created_at: dt.datetime,
    updated_at: dt.datetime,
) -> StoredTargetIcp:
    return StoredTargetIcp(
        target_icp_id=target_icp_id,
        account_id=account_id,
        label=label,
        status=status,
        matching_revision=matching_revision,
        plan_limit_code=plan_limit_code,
        plan_limited_at=plan_limited_at,
        customer_input=customer_input,
        missing_fields=customer_input.missing_fields(),
        created_at=created_at,
        updated_at=updated_at,
    )


def _row_to_stored(row: sa.Row) -> StoredTargetIcp:
    customer_input = TargetIcpInput.model_validate(row.customer_input)
    return _stored(
        row.target_icp_id,
        row.account_id,
        row.label,
        row.status,
        row.matching_revision,
        row.plan_limit_code,
        _aware(row.plan_limited_at) if row.plan_limited_at is not None else None,
        customer_input,
        _aware(row.created_at),
        _aware(row.updated_at),
    )
