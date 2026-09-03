"""Transactional first-party click and signup attribution."""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from signals.accounts.schema import account_landing_signal
from signals.conversion.contracts import (
    ATTRIBUTION_POLICY_VERSION,
    ATTRIBUTION_WINDOW,
    CONVERSION_EVENT_VERSION,
    ConversionMilestone,
)
from signals.conversion.source import AttributionSourceResolver
from signals.conversion.token import AttributionTokenKeyring, IssuedAttributionToken
from signals.decision_engine.policy import semantic_fingerprint
from signals.persistence.schema import acquisition_conversion_event, acquisition_conversion_journey


@dataclasses.dataclass(frozen=True)
class ClickResult:
    conversion_event_ref: str
    token_fingerprint: str
    expires_at: dt.datetime
    replayed: bool


@dataclasses.dataclass(frozen=True)
class JourneyResult:
    journey_ref: str
    account_id: str
    source_click_event_ref: str
    campaign_ref: str
    member_ref: str
    acquisition_opportunity_id: str


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


class ConversionAttributionService:
    """No clock, browser, or network authority is hidden in this service."""

    def __init__(
        self,
        engine: sa.Engine,
        keyring: AttributionTokenKeyring,
        *,
        source_resolver: AttributionSourceResolver | None = None,
    ) -> None:
        self.engine = engine
        self.keyring = keyring
        self.source_resolver = source_resolver or AttributionSourceResolver(engine)

    def record_click(self, raw_token: str, *, at: dt.datetime) -> ClickResult:
        with self.engine.begin() as connection:
            return self.record_click_in_transaction(connection, raw_token=raw_token, at=at)

    def record_click_in_transaction(
        self, connection: sa.Connection, *, raw_token: str, at: dt.datetime
    ) -> ClickResult:
        verified = self._verify_in_transaction(connection, raw_token=raw_token, at=at)
        event_ref = semantic_fingerprint(
            {
                "kind": CONVERSION_EVENT_VERSION,
                "milestone": ConversionMilestone.CLICK.value,
                "token_fingerprint": verified.token_fingerprint,
            }
        )
        existing = connection.execute(
            sa.select(acquisition_conversion_event).where(
                acquisition_conversion_event.c.conversion_event_ref == event_ref
            )
        ).mappings().one_or_none()
        if existing is not None:
            return ClickResult(
                conversion_event_ref=event_ref,
                token_fingerprint=verified.token_fingerprint,
                expires_at=verified.payload.expires_at,
                replayed=True,
            )
        payload = verified.payload
        values = {
            "conversion_event_ref": event_ref,
            "journey_ref": None,
            "milestone": ConversionMilestone.CLICK.value,
            "event_version": CONVERSION_EVENT_VERSION,
            "event_fingerprint": event_ref,
            "token_fingerprint": verified.token_fingerprint,
            "trigger_ref_type": "ATTRIBUTION_TOKEN",
            "trigger_ref": verified.token_fingerprint,
            "account_id": None,
            "campaign_ref": payload.campaign_ref,
            "member_ref": payload.member_ref,
            "acquisition_opportunity_id": payload.acquisition_opportunity_id,
            "occurred_at": at,
            "observed_at": at,
            "recorded_at": at,
        }
        try:
            with connection.begin_nested():
                connection.execute(sa.insert(acquisition_conversion_event).values(**values))
        except IntegrityError:
            existing = connection.execute(
                sa.select(acquisition_conversion_event.c.conversion_event_ref).where(
                    acquisition_conversion_event.c.conversion_event_ref == event_ref
                )
            ).scalar_one_or_none()
            if existing is None:
                raise
            return ClickResult(
                conversion_event_ref=event_ref,
                token_fingerprint=verified.token_fingerprint,
                expires_at=payload.expires_at,
                replayed=True,
            )
        return ClickResult(
            conversion_event_ref=event_ref,
            token_fingerprint=verified.token_fingerprint,
            expires_at=payload.expires_at,
            replayed=False,
        )

    def bind_signup_in_transaction(
        self,
        connection: sa.Connection,
        *,
        account_id: str,
        raw_token: str,
        at: dt.datetime,
    ) -> JourneyResult | None:
        current = self._journey_for_account(connection, account_id)
        if current is not None:
            return current
        try:
            verified = self._verify_in_transaction(connection, raw_token=raw_token, at=at)
        except ValueError:
            return None
        click = connection.execute(
            sa.select(acquisition_conversion_event).where(
                acquisition_conversion_event.c.milestone == ConversionMilestone.CLICK.value,
                acquisition_conversion_event.c.token_fingerprint
                == verified.token_fingerprint,
            )
        ).mappings().one_or_none()
        if click is None:
            return None
        clicked_at = _aware(click["occurred_at"])
        observed = _aware(at)
        eligible_until = min(clicked_at + ATTRIBUTION_WINDOW, verified.payload.expires_at)
        if observed < clicked_at or observed > eligible_until:
            return None

        payload = verified.payload
        journey_ref = semantic_fingerprint(
            {
                "kind": "conversion-journey-v1",
                "account_id": account_id,
                "source_click_event_ref": click["conversion_event_ref"],
            }
        )
        source_fingerprint = semantic_fingerprint(
            {
                "kind": "conversion-attribution-source-v1",
                "token_fingerprint": verified.token_fingerprint,
                "campaign_ref": payload.campaign_ref,
                "member_ref": payload.member_ref,
                "opportunity_id": payload.acquisition_opportunity_id,
                "country": payload.country,
                "sector_ref": payload.sector_ref,
                "need_ref": payload.need_ref,
                "wedge": payload.wedge,
            }
        )
        journey_values = {
            "journey_ref": journey_ref,
            "account_id": account_id,
            "source_click_event_ref": click["conversion_event_ref"],
            "campaign_ref": payload.campaign_ref,
            "member_ref": payload.member_ref,
            "acquisition_opportunity_id": payload.acquisition_opportunity_id,
            "token_fingerprint": verified.token_fingerprint,
            "token_version": verified.token_version,
            "token_key_version": verified.key_version,
            "country": payload.country,
            "sector_ref": payload.sector_ref,
            "sector_version": "conversion-sector-ref-v1",
            "need_ref": payload.need_ref,
            "need_version": payload.need_version,
            "wedge": payload.wedge,
            "wedge_version": payload.wedge_version,
            "attribution_policy_version": ATTRIBUTION_POLICY_VERSION,
            "source_fingerprint": source_fingerprint,
            "clicked_at": clicked_at,
            "attribution_expires_at": eligible_until,
            "signed_up_at": observed,
            "created_at": observed,
        }
        signup_ref = semantic_fingerprint(
            {
                "kind": CONVERSION_EVENT_VERSION,
                "milestone": ConversionMilestone.SIGNUP.value,
                "journey_ref": journey_ref,
            }
        )
        signup_values = {
            "conversion_event_ref": signup_ref,
            "journey_ref": journey_ref,
            "milestone": ConversionMilestone.SIGNUP.value,
            "event_version": CONVERSION_EVENT_VERSION,
            "event_fingerprint": signup_ref,
            "token_fingerprint": verified.token_fingerprint,
            "trigger_ref_type": "ACCOUNT_CREATED",
            "trigger_ref": account_id,
            "account_id": account_id,
            "campaign_ref": payload.campaign_ref,
            "member_ref": payload.member_ref,
            "acquisition_opportunity_id": payload.acquisition_opportunity_id,
            "occurred_at": observed,
            "observed_at": observed,
            "recorded_at": observed,
        }
        try:
            with connection.begin_nested():
                connection.execute(
                    sa.insert(acquisition_conversion_journey).values(**journey_values)
                )
                connection.execute(sa.insert(acquisition_conversion_event).values(**signup_values))
        except IntegrityError:
            current = self._journey_for_account(connection, account_id)
            if current is None:
                raise
            return current
        return JourneyResult(
            journey_ref=journey_ref,
            account_id=account_id,
            source_click_event_ref=click["conversion_event_ref"],
            campaign_ref=payload.campaign_ref,
            member_ref=payload.member_ref,
            acquisition_opportunity_id=payload.acquisition_opportunity_id,
        )

    def verify_in_transaction(
        self, connection: sa.Connection, *, raw_token: str, at: dt.datetime
    ) -> IssuedAttributionToken:
        """La charge signée, reconstruite depuis des faits que Kivou possède.

        Publique parce que l'atterrissage a besoin de SAVOIR ce que le mail
        promettait — l'opportunité, le pays, le besoin — avant même qu'un compte
        existe. Elle ne lit aucune horloge et n'ouvre aucune transaction.
        """
        return self._verify_in_transaction(connection, raw_token=raw_token, at=at)

    def landed_account_in_transaction(
        self, connection: sa.Connection, *, token_fingerprint: str
    ) -> str | None:
        """Le compte déjà CRÉÉ par un atterrissage de ce même jeton, s'il existe.

        La restriction aux comptes porteurs d'une ligne d'atterrissage n'est pas
        cosmétique : sans elle, un lien transféré rouvrirait une session sur le
        compte de quelqu'un qui s'est inscrit lui-même, avec son adresse et son
        mot de passe. Un lien magique ne doit jamais donner plus que ce qu'il a
        lui-même créé.
        """
        return connection.execute(
            sa.select(acquisition_conversion_journey.c.account_id)
            .select_from(
                acquisition_conversion_journey.join(
                    account_landing_signal,
                    account_landing_signal.c.account_id
                    == acquisition_conversion_journey.c.account_id,
                )
            )
            .where(acquisition_conversion_journey.c.token_fingerprint == token_fingerprint)
            .order_by(acquisition_conversion_journey.c.created_at)
            .limit(1)
        ).scalar_one_or_none()

    def _verify_in_transaction(
        self, connection: sa.Connection, *, raw_token: str, at: dt.datetime
    ) -> IssuedAttributionToken:
        lookup = self.keyring.parse(raw_token)
        payload = self.source_resolver.for_member(connection, lookup.member_ref)
        return self.keyring.verify(raw_token, payload=payload, at=at)

    @staticmethod
    def _journey_for_account(
        connection: sa.Connection, account_id: str
    ) -> JourneyResult | None:
        row = connection.execute(
            sa.select(acquisition_conversion_journey).where(
                acquisition_conversion_journey.c.account_id == account_id
            )
        ).mappings().one_or_none()
        if row is None:
            return None
        return JourneyResult(
            journey_ref=row["journey_ref"],
            account_id=row["account_id"],
            source_click_event_ref=row["source_click_event_ref"],
            campaign_ref=row["campaign_ref"],
            member_ref=row["member_ref"],
            acquisition_opportunity_id=row["acquisition_opportunity_id"],
        )


__all__ = [
    "ClickResult",
    "ConversionAttributionService",
    "JourneyResult",
]
