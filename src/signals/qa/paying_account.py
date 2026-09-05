"""Build the long-lived paying staging account used by product acceptance."""

from __future__ import annotations

import datetime as dt
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import sqlalchemy as sa

from signals.accounts import service as accounts
from signals.accounts.icp_input import MonetaryThreshold, TargetIcpInput
from signals.accounts.schema import account, auth_user
from signals.billing import catalogue
from signals.billing.gateway import StripeSubscriptionState
from signals.billing.service import synchronize_subscription
from signals.companies.schema import saas_company
from signals.companies.service import ensure_companies_for_signal_keys
from signals.engagement import company as company_engagement
from signals.persistence.database import create_database_engine
from signals.persistence.identity import signal_key
from signals.persistence.materialization import content_fingerprint
from signals.persistence.schema import materialized_signal

DEFAULT_SIGNAL_COUNT = 1_002
DEFAULT_CONTACT_COUNT = 50
DEFAULT_NOTE_COUNT = 20


@dataclass(frozen=True)
class PayingRecipeResult:
    account_id: str
    profile_count: int
    signal_count: int
    contact_count: int
    note_count: int


def _profiles() -> tuple[tuple[str, TargetIcpInput], ...]:
    return (
        (
            "Bardage métallique · Isère",
            TargetIcpInput(
                offer_summary="Bardage métallique pour les entreprises de construction",
                offers=("materials_and_components",),
                buyer_trades=("building_construction",),
                territories=("FR",),
                territory_subdivisions=("FR-38",),
                sector_cpv_prefixes=("45",),
                minimum_contract_value=MonetaryThreshold(currency="EUR", minimum_amount=0),
            ),
        ),
        (
            "CVC plomberie · PACA",
            TargetIcpInput(
                offer_summary="Installations CVC et plomberie pour les chantiers",
                offers=("specialist_subcontracting",),
                buyer_trades=("technical_installations",),
                territories=("FR",),
                territory_subdivisions=("FR-13",),
                sector_cpv_prefixes=("45",),
                minimum_contract_value=MonetaryThreshold(currency="EUR", minimum_amount=0),
            ),
        ),
    )


def _source_rows(
    connection: sa.Connection, *, count: int, now: dt.datetime
) -> list[sa.Row]:
    rows = connection.execute(
        sa.select(materialized_signal)
        .where(
            materialized_signal.c.invalidated_at.is_(None),
            materialized_signal.c.winner_name.is_not(None),
        )
        .order_by(materialized_signal.c.created_at.desc(), materialized_signal.c.signal_key)
    ).all()
    selected: list[sa.Row] = []
    candidate_limit = count * 2
    opportunities: set[str] = set()
    for row in rows:
        if row.opportunity_key in opportunities:
            continue
        opportunities.add(row.opportunity_key)
        selected.append(row)
        if len(selected) == candidate_limit:
            break
    if len(selected) < count:
        raise ValueError(f"only {len(selected)} suitable source signals for requested {count}")
    keys = tuple(row.signal_key for row in selected)
    ensure_companies_for_signal_keys(connection, signal_keys=keys, now=now)
    refreshed = {
        row.signal_key: row
        for row in connection.execute(
            sa.select(materialized_signal).where(materialized_signal.c.signal_key.in_(keys))
        ).all()
    }
    return [refreshed[key] for key in keys[:count]]


def _clone_signals(
    connection: sa.Connection,
    *,
    profile_ids: tuple[str, str],
    source_rows: list[sa.Row],
    now: dt.datetime,
) -> tuple[str, ...]:
    created: list[str] = []
    for index, source in enumerate(source_rows):
        profile_id = profile_ids[index % len(profile_ids)]
        values = dict(source._mapping)
        values.update(
            signal_key=signal_key(source.opportunity_key, target_icp_id=profile_id),
            target_icp_id=profile_id,
            target_icp_revision=1,
            invalidated_at=None,
            invalidation_reason=None,
            revision=1,
            materialized_at=now - dt.timedelta(minutes=index),
            created_at=now - dt.timedelta(minutes=index),
        )
        values["content_fingerprint"] = content_fingerprint(values)
        connection.execute(sa.insert(materialized_signal).values(**values))
        created.append(values["signal_key"])
    return tuple(created)


def build_paying_recipe_account(
    engine: sa.Engine,
    *,
    email: str,
    password: str,
    now: dt.datetime,
    signal_count: int = DEFAULT_SIGNAL_COUNT,
    contact_count: int = DEFAULT_CONTACT_COUNT,
    note_count: int = DEFAULT_NOTE_COUNT,
) -> PayingRecipeResult:
    """Atomically rebuild the one disposable paying acceptance account."""
    if signal_count <= 0 or contact_count < 0 or note_count < 0:
        raise ValueError("fixture counts must be positive")
    if note_count > contact_count:
        raise ValueError("notes require at least as many contacted companies")

    created_at = now - dt.timedelta(days=90)
    with engine.begin() as connection:
        normalized_email = accounts.normalize_email(email)
        existing_account_id = connection.scalar(
            sa.select(auth_user.c.account_id).where(
                auth_user.c.email_normalized == normalized_email
            )
        )
        if existing_account_id is not None:
            connection.execute(
                sa.delete(account).where(account.c.account_id == existing_account_id)
            )

        session = accounts.sign_up(
            connection,
            email=email,
            password=password,
            company_name="Kivou QA · Client Essential 3 mois",
            locale="fr",
            now=created_at,
            session_ttl=dt.timedelta(minutes=1),
        )
        profiles = tuple(
            accounts.create_target_icp(
                connection,
                account_id=session.account_id,
                label=label,
                customer_input=customer_input,
                now=created_at + dt.timedelta(minutes=index + 1),
            ).target_icp_id
            for index, (label, customer_input) in enumerate(_profiles())
        )
        synchronize_subscription(
            connection,
            StripeSubscriptionState(
                subscription_id=f"sub_qa_{session.account_id}",
                customer_id=f"cus_qa_{session.account_id}",
                status="active",
                price_id="price_qa_essential_chf",
                product_id="prod_qa_essential",
                lookup_key=catalogue.lookup_key_for("essential", "chf"),
                currency="chf",
                current_period_start=created_at,
                current_period_end=now + dt.timedelta(days=30),
                cancel_at_period_end=False,
                canceled_at=None,
                scheduled_cancellation_at=None,
                livemode=False,
                account_id=session.account_id,
            ),
            account_id=session.account_id,
            event_created_at=created_at,
            expect_livemode=False,
            now=created_at,
        )

        sources = _source_rows(connection, count=signal_count, now=now)
        _clone_signals(
            connection,
            profile_ids=(profiles[0], profiles[1]),
            source_rows=sources,
            now=now,
        )
        company_keys = tuple(
            connection.execute(
                sa.select(saas_company.c.company_key)
                .where(
                    saas_company.c.identity_fingerprint.in_(
                        {row.company_identity_fingerprint for row in sources}
                    )
                )
                .order_by(saas_company.c.company_key)
                .limit(contact_count)
            ).scalars()
        )
        if len(company_keys) < contact_count:
            raise ValueError(
                f"only {len(company_keys)} companies for requested {contact_count} contacts"
            )
        for index, company_key in enumerate(company_keys):
            event_at = now - dt.timedelta(days=7, minutes=index)
            company_engagement.set_contact(
                connection,
                account_id=session.account_id,
                company_key=company_key,
                status="contacted",
                now=event_at,
            )
            if index < note_count:
                company_engagement.put_note(
                    connection,
                    account_id=session.account_id,
                    company_key=company_key,
                    body=f"Note de recette {index + 1}",
                    now=event_at,
                )

        return PayingRecipeResult(
            account_id=session.account_id,
            profile_count=len(profiles),
            signal_count=len(sources),
            contact_count=len(company_keys),
            note_count=note_count,
        )


def main(
    *,
    environ: Mapping[str, str] | None = None,
    engine_factory: Callable[[], sa.Engine] = create_database_engine,
) -> int:
    environment = os.environ if environ is None else environ
    if environment.get("KIVOU_ENV", "").casefold() == "production":
        print("error=production_forbidden", file=sys.stderr)
        return 2
    email = environment.get("KIVOU_QA_PAYING_EMAIL", "").strip()
    password = environment.get("KIVOU_QA_PAYING_PASSWORD", "")
    if not email or not password:
        print("error=missing_qa_credentials", file=sys.stderr)
        return 2
    result = build_paying_recipe_account(
        engine_factory(), email=email, password=password, now=dt.datetime.now(dt.UTC)
    )
    print(
        f"account_id={result.account_id} profiles={result.profile_count} "
        f"signals={result.signal_count} contacted={result.contact_count} notes={result.note_count}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
