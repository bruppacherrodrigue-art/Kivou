"""Le jugement du client sur un signal — stocké, jamais rebouclé sur le moteur.

La règle qui gouverne tout le module (§2)
─────────────────────────────────────────
    RETOUR CLIENT  →  STOCKER  →  ANALYSER  →  R&D SUPERVISÉE

et jamais « le client clique 👎 → le score se réécrit ». Un moteur qui
apprend sans surveillance de quelques dizaines d'avis apprend surtout le
biais des premiers clients, et le fait silencieusement. SPEC-014 fabrique la
matière première ; l'exploiter reste un travail supervisé, plus tard.

« Contacté » n'est pas « pertinent » (§6)
────────────────────────────────────────
Un client peut juger un signal excellent sans avoir encore appelé. Confondre
les deux effacerait la seule mesure qui compte vraiment — celle d'une
démarche commerciale réellement entreprise.

Ce que le client voyait au moment de juger (§32)
───────────────────────────────────────────────
Le statut d'événement et l'âge du signal sont figés AU MOMENT du jugement.
Sans cela, un « trop tard » deviendrait inanalysable : recalculé à la date
du jour, il donnerait un autre âge, et l'on ne saurait plus si le client
trouvait tard un signal de trois jours ou de trois mois.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.billing.service import BillingError
from signals.engagement import analytics
from signals.engagement.schema import (
    MAXIMUM_NOTE_LENGTH,
    NEGATIVE_REASON_CODES,
    RELEVANCE_VALUES,
    signal_feedback,
)

FEEDBACK_VERSION = "kivou-feedback-v0.1"


class InvalidFeedback(BillingError):
    """Un jugement que le vocabulaire n'admet pas."""

    code = "invalid_feedback"


class SignalNotAccessible(BillingError):
    """§30 — le signal n'est pas lisible par ce compte : ni possédé, ni débloqué.

    Un aperçu verrouillé ne contient pas de quoi juger une piste commerciale.
    Accepter un avis dessus ferait du formulaire de retour un oracle : « ce
    signal est-il pertinent ? » finirait par renseigner sur ce qu'il cache.
    """

    code = "signal_not_accessible"


@dataclasses.dataclass(frozen=True)
class StoredFeedback:
    """L'état courant du jugement d'un compte sur un signal."""

    account_id: str
    signal_key: str
    relevance: str
    reason_code: str | None
    note: str | None
    contacted_at: dt.datetime | None
    event_status_at_feedback: str | None
    event_age_days_at_feedback: int | None
    signal_revision_at_feedback: int | None
    opportunity_key: str | None
    target_icp_id: str | None
    created_at: dt.datetime
    updated_at: dt.datetime

    @property
    def contacted(self) -> bool:
        return self.contacted_at is not None


def validate(relevance: str, reason_code: str | None, note: str | None) -> None:
    """§7 — un jugement positif n'a pas de raison, un refus en exige une.

    Les deux contraintes disent la même chose : une raison sans refus n'a aucun
    sens à analyser, et un refus sans raison n'apprend rien.
    """
    if relevance not in RELEVANCE_VALUES:
        raise InvalidFeedback(f"jugement inconnu : {relevance!r} (attendu {RELEVANCE_VALUES})")
    if relevance == "relevant":
        if reason_code is not None:
            raise InvalidFeedback("un signal jugé pertinent ne porte pas de raison de refus")
    elif reason_code is None:
        raise InvalidFeedback("un refus doit dire pourquoi")
    elif reason_code not in NEGATIVE_REASON_CODES:
        raise InvalidFeedback(
            f"raison inconnue : {reason_code!r} (attendu {NEGATIVE_REASON_CODES})"
        )
    if note is not None and len(note) > MAXIMUM_NOTE_LENGTH:
        raise InvalidFeedback(f"note trop longue : {MAXIMUM_NOTE_LENGTH} caractères maximum")


def _row(row: sa.Row) -> StoredFeedback:
    from signals.billing.service import aware_datetime

    return StoredFeedback(
        account_id=row.account_id,
        signal_key=row.signal_key,
        relevance=row.relevance,
        reason_code=row.reason_code,
        note=row.note,
        contacted_at=aware_datetime(row.contacted_at),
        event_status_at_feedback=row.event_status_at_feedback,
        event_age_days_at_feedback=row.event_age_days_at_feedback,
        signal_revision_at_feedback=row.signal_revision_at_feedback,
        opportunity_key=row.opportunity_key,
        target_icp_id=row.target_icp_id,
        created_at=aware_datetime(row.created_at),
        updated_at=aware_datetime(row.updated_at),
    )


def get_feedback(
    connection: sa.Connection, *, account_id: str, signal_key: str
) -> StoredFeedback | None:
    row = connection.execute(
        sa.select(signal_feedback).where(
            signal_feedback.c.account_id == account_id,
            signal_feedback.c.signal_key == signal_key,
        )
    ).first()
    return None if row is None else _row(row)


def feedback_by_signal(
    connection: sa.Connection, *, account_id: str
) -> dict[str, StoredFeedback]:
    """Toutes les lignes de retour du compte, indexées par signal — une requête.

    Le statut unifié (`engagement.status`) se dérive par signal ; le lire un
    par un ferait un N+1 sur chaque page du feed.
    """
    rows = connection.execute(
        sa.select(signal_feedback).where(signal_feedback.c.account_id == account_id)
    ).all()
    return {row.signal_key: _row(row) for row in rows}


@dataclasses.dataclass(frozen=True)
class SignalContext:
    """Ce que le client avait sous les yeux — figé, jamais recalculé (§32)."""

    signal_key: str
    opportunity_key: str
    target_icp_id: str
    revision: int
    event_status: str
    event_age_days: int | None


def put_feedback(
    connection: sa.Connection,
    *,
    account_id: str,
    context: SignalContext,
    relevance: str,
    reason_code: str | None,
    note: str | None,
    now: dt.datetime,
    user_id: str | None = None,
) -> StoredFeedback:
    """Enregistre — ou remplace — le jugement courant, et l'observe.

    L'état courant est écrasé, l'événement est ajouté : le client peut changer
    d'avis sans que la raison qu'il avait donnée disparaisse de l'analyse.
    """
    validate(relevance, reason_code, note)
    existing = get_feedback(connection, account_id=account_id, signal_key=context.signal_key)

    values = {
        "relevance": relevance,
        "reason_code": reason_code,
        "note": note,
        "event_status_at_feedback": context.event_status,
        "event_age_days_at_feedback": context.event_age_days,
        "signal_revision_at_feedback": context.revision,
        "opportunity_key": context.opportunity_key,
        "target_icp_id": context.target_icp_id,
        "updated_at": now,
    }
    if existing is None:
        connection.execute(
            sa.insert(signal_feedback).values(
                account_id=account_id,
                signal_key=context.signal_key,
                contacted_at=None,
                created_at=now,
                **values,
            )
        )
    else:
        connection.execute(
            sa.update(signal_feedback)
            .where(
                signal_feedback.c.account_id == account_id,
                signal_feedback.c.signal_key == context.signal_key,
            )
            .values(**values)
        )

    analytics.record(
        connection,
        account_id=account_id,
        user_id=user_id,
        target_icp_id=context.target_icp_id,
        signal_key=context.signal_key,
        event_type=(
            "signal_feedback_relevant"
            if relevance == "relevant"
            else "signal_feedback_not_relevant"
        ),
        occurred_at=now,
        properties={
            "reason_code": reason_code,
            "event_status": context.event_status,
            "event_age_days": context.event_age_days,
            "signal_revision": context.revision,
            "has_note": note is not None,
            "updated": existing is not None,
        },
    )
    return get_feedback(connection, account_id=account_id, signal_key=context.signal_key)


def mark_contacted(
    connection: sa.Connection,
    *,
    account_id: str,
    context: SignalContext,
    now: dt.datetime,
    user_id: str | None = None,
) -> tuple[StoredFeedback, bool]:
    """Marque le signal comme contacté. Rend l'état et s'il a CHANGÉ.

    §12 — l'action est idempotente : le second appel ne déplace pas la date et
    n'enregistre pas un second événement. Deux clics sur un bouton ne font pas
    deux démarches commerciales, et l'étoile polaire ne doit pas les compter
    comme telles.
    """
    existing = get_feedback(connection, account_id=account_id, signal_key=context.signal_key)
    if existing is not None and existing.contacted_at is not None:
        return existing, False

    if existing is None:
        # Contacter sans avoir jugé est légitime : on enregistre l'action, et le
        # jugement reste à donner. `relevance` ne peut pas être nul en base, et
        # `relevant` est le seul sens qu'un contact puisse avoir.
        connection.execute(
            sa.insert(signal_feedback).values(
                account_id=account_id,
                signal_key=context.signal_key,
                relevance="relevant",
                reason_code=None,
                note=None,
                contacted_at=now,
                event_status_at_feedback=context.event_status,
                event_age_days_at_feedback=context.event_age_days,
                signal_revision_at_feedback=context.revision,
                opportunity_key=context.opportunity_key,
                target_icp_id=context.target_icp_id,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        connection.execute(
            sa.update(signal_feedback)
            .where(
                signal_feedback.c.account_id == account_id,
                signal_feedback.c.signal_key == context.signal_key,
            )
            .values(contacted_at=now, updated_at=now)
        )

    analytics.record(
        connection,
        account_id=account_id,
        user_id=user_id,
        target_icp_id=context.target_icp_id,
        signal_key=context.signal_key,
        event_type="signal_contacted",
        occurred_at=now,
        properties={
            "event_status": context.event_status,
            "event_age_days": context.event_age_days,
            "signal_revision": context.revision,
        },
    )
    return get_feedback(connection, account_id=account_id, signal_key=context.signal_key), True


# ─── §31 — l'export d'apprentissage, interne et déterministe ──────────────────


@dataclasses.dataclass(frozen=True)
class LearningRow:
    """Une ligne d'analyse pour la R&D « besoin résiduel post-attribution ».

    Aucune donnée personnelle : ni e-mail, ni mot de passe, ni jeton. Le compte
    n'est qu'un identifiant technique, utile pour ne pas confondre deux clients.
    """

    signal_key: str
    opportunity_key: str | None
    account_id: str
    target_icp_id: str | None
    relevance: str
    reason_code: str | None
    contacted: bool
    event_status_at_feedback: str | None
    event_age_days_at_feedback: int | None
    signal_revision_at_feedback: int | None
    feedback_at: dt.datetime


def learning_export(
    connection: sa.Connection,
    *,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> tuple[LearningRow, ...]:
    """L'export d'apprentissage — fonction interne, jamais exposée en API (§31).

    Elle ne déclenche aucun entraînement : elle rend des lignes qu'un humain
    lira. Le jour où une règle changera, ce sera parce que quelqu'un l'aura
    décidé en regardant ces lignes.
    """
    query = sa.select(signal_feedback).order_by(
        signal_feedback.c.updated_at, signal_feedback.c.signal_key
    )
    if start is not None:
        query = query.where(signal_feedback.c.updated_at >= start)
    if end is not None:
        query = query.where(signal_feedback.c.updated_at < end)

    rows = []
    for row in connection.execute(query).all():
        stored = _row(row)
        rows.append(
            LearningRow(
                signal_key=stored.signal_key,
                opportunity_key=stored.opportunity_key,
                account_id=stored.account_id,
                target_icp_id=stored.target_icp_id,
                relevance=stored.relevance,
                reason_code=stored.reason_code,
                contacted=stored.contacted,
                event_status_at_feedback=stored.event_status_at_feedback,
                event_age_days_at_feedback=stored.event_age_days_at_feedback,
                signal_revision_at_feedback=stored.signal_revision_at_feedback,
                feedback_at=stored.updated_at,
            )
        )
    return tuple(rows)
