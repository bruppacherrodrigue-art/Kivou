from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa

from signals.client_value.history import (
    AwardFact,
    directory_history_and_markets,
    history_for_company,
    markets_for_company,
    summarize_awards,
)
from signals.companies.schema import saas_company
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
        identifiers = connection.scalar(
            sa.select(saas_company.c.official_identifiers).where(
                saas_company.c.company_key == company_key
            )
        )
        siren = next(
            identifier["value"][:9] for identifier in identifiers if identifier["scheme"] == "SIRET"
        )

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
        connection.execute(sa.update(source_event).values(source_url="javascript:alert(1)"))
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
        identified_history, identified_markets = directory_history_and_markets(
            connection,
            siren=siren,
            winner_name="nom du registre différent du libellé d'attribution",
            department="38",
            as_of=AS_OF,
        )

    assert exact is not None and exact["resolution"] == "company_key"
    assert fallback is not None
    assert fallback["resolution_note"] == "rapprochement par nom"
    assert wrong_department is None
    assert markets and "source_url" not in markets[0]
    assert combined_history == fallback
    assert combined_markets == markets
    assert identified_history == exact
    assert identified_markets == markets


@pytest.mark.parametrize("binding", ["registered", "unregistered", "quarantined", "contradictory"])
@pytest.mark.parametrize("reader", ["canonical", "directory"])
def test_exact_legacy_boamp_identifier_never_scans_name_fallback(
    tmp_path, monkeypatch, reader, binding
) -> None:
    from feed_helpers import BOAMP_AGING, boamp_award, make_account, make_icp, materialize

    from signals.client_value import history
    from signals.client_value.company_identity import exact_french_siren, register_alias
    from signals.engagement.prospecting_schema import company_subject_alias

    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'legacy-history.db'}")
    migrate_to_latest(engine)
    fallback_calls = []
    fallback = history._fallback_award_rows

    def record_fallback(*args, **kwargs):
        fallback_calls.append(True)
        return fallback(*args, **kwargs)

    monkeypatch.setattr(history, "_fallback_award_rows", record_fallback)
    with engine.begin() as connection:
        owner = make_account(connection, "legacy-history@example.test", "Client synthétique")
        profile = make_icp(connection, owner, territories=("FR",))
        event, awards = boamp_award(BOAMP_AGING)
        payload = awards[0].model_dump(mode="python")
        for party in payload["awardee_parties"]:
            for member in party["members"]:
                for identifier in member["organization"]["identifiers"]:
                    if identifier["scheme"] == "SIRET":
                        value = identifier["value"]
                        identifier.update(
                            scheme="BOAMP-COMPANY-ID",
                            value=f"{value[:3]} {value[3:6]} {value[6:9]} {value[9:]}",
                        )
        award = type(awards[0]).model_validate(payload)
        signal = materialize(connection, event, award, target_icp_id=profile)
        alias = ensure_companies_for_signal_keys(
            connection,
            signal_keys=(signal.signal_key,),
            now=dt.datetime(2026, 9, 11, tzinfo=dt.UTC),
        )[signal.signal_key]
        identifiers = connection.scalar(
            sa.select(saas_company.c.official_identifiers).where(
                saas_company.c.company_key == alias
            )
        )
        siren = exact_french_siren(identifiers, country="FR")
        assert siren is not None
        canonical = register_alias(
            connection, company_key=alias, siren=siren, now=dt.datetime(2026, 9, 11, tzinfo=dt.UTC)
        )
        assert canonical != alias
        if binding == "unregistered":
            connection.execute(sa.delete(company_subject_alias))
        elif binding == "quarantined":
            register_alias(
                connection,
                company_key=alias,
                siren="732829320",
                now=dt.datetime(2026, 9, 11, tzinfo=dt.UTC),
            )
        elif binding == "contradictory":
            connection.execute(
                sa.update(company_subject_alias)
                .where(company_subject_alias.c.alias_company_key == alias)
                .values(
                    canonical_company_key="cmp_directory_732829320", identifier_value="732829320"
                )
            )
        assert (
            connection.scalar(
                sa.select(saas_company.c.company_key).where(saas_company.c.company_key == canonical)
            )
            is None
        )
        expected = history_for_company(
            connection, company_key=alias, winner_name=None, department=None, as_of=AS_OF
        )
        assert expected is not None
        if reader == "canonical":
            actual = history_for_company(
                connection,
                company_key=canonical,
                winner_name="SARL ALCIS TRANSPORTS",
                department="31",
                as_of=AS_OF,
            )
        else:
            actual, markets = directory_history_and_markets(
                connection,
                siren=siren,
                winner_name="SARL ALCIS TRANSPORTS",
                department="31",
                as_of=AS_OF,
            )
        assert fallback_calls == [], (
            "an exact legacy identifier must not trigger the global award scan"
        )
        blocked = binding in {"quarantined", "contradictory"}
        assert actual == (None if blocked else expected)
        if reader == "directory":
            assert len(markets) == (0 if blocked else 1)


def test_siren_history_aggregates_valid_establishments_without_rehabilitating_quarantine(
    tmp_path, monkeypatch
) -> None:
    from feed_helpers import BOAMP_AGING, boamp_award, make_account, make_icp, materialize

    from signals.client_value import history
    from signals.client_value.company_identity import exact_french_siren, register_alias

    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'group-history.db'}")
    migrate_to_latest(engine)
    siren = "479673980"
    sirets = [
        f"{siren}{nic:05d}"
        for nic in range(1, 60)
        if exact_french_siren([{"scheme": "SIRET", "value": f"{siren}{nic:05d}"}], country="FR")
        == siren
    ]
    assert len(sirets) >= 6
    fallback_calls = []
    fallback = history._fallback_award_rows

    def record_fallback(*args, **kwargs):
        fallback_calls.append(True)
        return fallback(*args, **kwargs)

    monkeypatch.setattr(history, "_fallback_award_rows", record_fallback)
    with engine.begin() as connection:
        owner = make_account(connection, "history-group@example.test", "Client synthétique")
        profile = make_icp(connection, owner, territories=("FR",))
        event, awards = boamp_award(BOAMP_AGING)
        variants = [
            (sirets[0], "FR", "registered"),
            (sirets[1], "FR", "unregistered"),
            (sirets[2], "FR", "quarantined"),
            ("73282932000074", "FR", "other_siren"),
            (sirets[3], "CH", "other_country"),
            (sirets[4], "FR", "ambiguous_identifiers"),
            (sirets[5], "FR", "contradictory_registry"),
            (sirets[0][:-1] + str((int(sirets[0][-1]) + 1) % 10), "FR", "invalid_siret"),
            (sirets[0][:9] + "-" + sirets[0][9:], "FR", "punctuation"),
        ]
        accepted_awards = set()
        for index, (value, country, kind) in enumerate(variants):
            payload = awards[0].model_dump(mode="python")
            payload["source_award_id"] = f"synthetic-history-{index}"
            organization = payload["awardee_parties"][0]["members"][0]["organization"]
            organization["country"] = country
            organization["identifiers"] = [
                {
                    "scheme": "BOAMP-COMPANY-ID",
                    "value": f"{value[:3]} {value[3:6]} {value[6:9]} {value[9:]}",
                }
            ]
            if kind == "ambiguous_identifiers":
                organization["identifiers"].append({"scheme": "SIRET", "value": "73282932000074"})
            award = type(awards[0]).model_validate(payload)
            signal = materialize(connection, event, award, target_icp_id=profile)
            alias = ensure_companies_for_signal_keys(
                connection,
                signal_keys=(signal.signal_key,),
                now=dt.datetime(2026, 9, 11, tzinfo=dt.UTC),
            )[signal.signal_key]
            if kind in {"registered", "quarantined"}:
                register_alias(
                    connection,
                    company_key=alias,
                    siren=siren,
                    now=dt.datetime(2026, 9, 11, tzinfo=dt.UTC),
                )
            if kind == "quarantined":
                register_alias(
                    connection,
                    company_key=alias,
                    siren="732829320",
                    now=dt.datetime(2026, 9, 11, tzinfo=dt.UTC),
                )
            if kind == "contradictory_registry":
                register_alias(
                    connection,
                    company_key=alias,
                    siren="732829320",
                    now=dt.datetime(2026, 9, 11, tzinfo=dt.UTC),
                )
            if kind in {"registered", "unregistered"}:
                accepted_awards.add(signal.materialization_award_key)
        summary, markets = directory_history_and_markets(
            connection,
            siren=siren,
            winner_name="SARL ALCIS TRANSPORTS",
            department="31",
            as_of=AS_OF,
        )
        canonical_summary = history_for_company(
            connection,
            company_key=f"cmp_directory_{siren}",
            winner_name="SARL ALCIS TRANSPORTS",
            department="31",
            as_of=AS_OF,
        )
    assert fallback_calls == []
    assert {market["market_id"] for market in markets} == accepted_awards
    assert summary == canonical_summary
    assert summary["last_12_months"]["awards_count"] == 2
