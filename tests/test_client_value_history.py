from __future__ import annotations

import datetime as dt
from decimal import Decimal

import sqlalchemy as sa

from signals.client_value.history import (
    AwardFact,
    directory_history_and_markets,
    history_for_company,
    markets_for_company,
    summarize_awards,
)
from signals.companies.service import ensure_companies_for_signal_keys
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import source_event

AS_OF = dt.date(2026, 9, 11)


def fact(
    key: str,
    date: dt.date | None,
    amount: str | None,
    buyer: str | None,
    *,
    consortium: bool = False,
    currency: str = "EUR",
) -> AwardFact:
    return AwardFact(
        award_key=key,
        known_date=date,
        amount=None if amount is None else Decimal(amount),
        currency=None if amount is None else currency,
        buyer_names=() if buyer is None else (buyer,),
        is_consortium=consortium,
    )


def test_summary_calculates_the_sellable_history_without_inventing_missing_money() -> None:
    result = summarize_awards(
        (
            fact("a", dt.date(2025, 1, 4), "10000", "Commune A"),
            fact("b", dt.date(2025, 10, 2), "12000", "Commune A", consortium=True),
            fact("c", dt.date(2026, 1, 8), None, "Département B"),
            fact("d", dt.date(2026, 6, 12), "18000", "Commune A", consortium=True),
            fact("e", None, "999999", None),
        ),
        as_of=AS_OF,
        resolution="company_key",
    )

    assert result == {
        "resolution": "company_key",
        "last_12_months": {
            "awards_count": 3,
            "total_amounts": [{"currency": "EUR", "value": "30000"}],
            "recurring_buyers": ["Commune A"],
        },
        "summary": {
            "first_award_at": "2025-01-04",
            "awards_per_quarter": "0.7",
            "median_amounts": [{"currency": "EUR", "value": "15000"}],
            "consortium_share": "0.4",
            "recurring_buyers": ["Commune A"],
        },
        "source": "public_awards",
    }


def test_name_resolution_is_disclosed_and_empty_history_is_absent() -> None:
    result = summarize_awards(
        (fact("a", dt.date(2026, 8, 1), None, None),),
        as_of=AS_OF,
        resolution="normalized_name_department",
    )

    assert result == {
        "resolution": "normalized_name_department",
        "resolution_note": "rapprochement par nom",
        "last_12_months": {"awards_count": 1},
        "summary": {
            "first_award_at": "2026-08-01",
            "awards_per_quarter": "1.0",
            "consortium_share": "0.0",
        },
        "source": "public_awards",
    }
    assert summarize_awards((), as_of=AS_OF, resolution="company_key") is None


def test_database_reader_prefers_company_key_then_supports_name_and_department(tmp_path) -> None:
    from feed_helpers import BOAMP_AGING, boamp_award, make_account, make_icp, materialize

    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'history.db'}")
    migrate_to_latest(engine)
    with engine.begin() as connection:
        account_id = make_account(connection, "history@example.test", "Client")
        target_icp_id = make_icp(
            connection,
            account_id,
            territories=("FR",),
            territory_subdivisions=("FR-31",),
        )
        event, awards = boamp_award(BOAMP_AGING)
        signal = materialize(connection, event, awards[0], target_icp_id=target_icp_id)
        company_key = ensure_companies_for_signal_keys(
            connection,
            signal_keys=(signal.signal_key,),
            now=dt.datetime(2026, 9, 11, 9, tzinfo=dt.UTC),
        )[signal.signal_key]

        exact = history_for_company(
            connection,
            company_key=company_key,
            winner_name="nom volontairement faux",
            department="31",
            as_of=AS_OF,
        )
        fallback = history_for_company(
            connection,
            company_key=None,
            winner_name="  SÀRL   Alcis transports ",
            department="31",
            as_of=AS_OF,
        )
        wrong_department = history_for_company(
            connection,
            company_key=None,
            winner_name="SARL ALCIS TRANSPORTS",
            department="38",
            as_of=AS_OF,
        )
        connection.execute(
            sa.update(source_event).values(source_url="javascript:alert(1)")
        )
        markets = markets_for_company(
            connection,
            winner_name="SARL ALCIS TRANSPORTS",
            department="31",
        )
        combined_history, combined_markets = directory_history_and_markets(
            connection,
            winner_name="SARL ALCIS TRANSPORTS",
            department="31",
            as_of=AS_OF,
        )

    assert exact is not None and exact["resolution"] == "company_key"
    assert fallback is not None
    assert fallback["resolution_note"] == "rapprochement par nom"
    assert wrong_department is None
    assert markets and "source_url" not in markets[0]
    assert combined_history == fallback
    assert combined_markets == markets
