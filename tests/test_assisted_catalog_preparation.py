from __future__ import annotations

import datetime as dt
import hashlib

import sqlalchemy as sa

from signals.acquisition_runtime.catalog_selection import (
    CatalogFamilyInventory,
    CatalogNotice,
)
from signals.persistence.schema import (
    acquisition_runtime_cycle,
    prospect_target,
    supplier_directory,
)
from signals.personalization.prospect_mail import RenderedProspectMail
from signals.prospection_actions.catalog_preparation import (
    AssistedCatalogPreparationService,
)
from signals.prospection_actions.preparation import AssistedSignal
from signals.prospection_actions.service import IssuedProspectLink

NOW = dt.datetime(2026, 9, 18, 9, tzinfo=dt.UTC)


class Links:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def issue(self, *, row, email: str, at: dt.datetime) -> IssuedProspectLink:
        self.calls.append((str(row["siren"]), str(row["opportunity_key"]), email))
        digest = hashlib.sha256(
            f"{row['target_id']}\0{row['opportunity_key']}\0{email}".encode()
        ).hexdigest()
        return IssuedProspectLink(
            url=f"https://kivou.eu/a/kat1.key.{digest}.signature",
            member_ref=digest,
            token_fingerprint=hashlib.sha256(digest.encode()).hexdigest(),
            payload={
                "member_ref": digest,
                "opportunity_key": row["opportunity_key"],
                "need_ref": row["family_key"],
                "issued_at": at.isoformat(),
            },
            unsubscribe_url=f"https://kivou.eu/unsubscribe/{digest}",
        )


def render(row: dict[str, object]) -> RenderedProspectMail:
    url = str(row["attribution_url"])
    family = str(row["family_key"])
    subject = str(row["signal_subject"])
    return RenderedProspectMail(
        subject=f"{family} — {subject}",
        text=f"{family} | {subject} | {url}",
        html=f"<p>{family} | {subject} | <a href=\"{url}\">{url}</a></p>",
        word_count=12,
        contract_status="passed",
        contract_failure=None,
    )


def signal(
    opportunity_key: str,
    family_key: str,
    *,
    department: str,
    subject: str,
    holder_siren: str,
) -> AssistedSignal:
    return AssistedSignal(
        opportunity_key=opportunity_key,
        acquisition_opportunity_id=hashlib.sha256(opportunity_key.encode()).hexdigest(),
        procedure_key=f"award-{opportunity_key}",
        holder=f"TITULAIRE {opportunity_key.upper()}",
        holder_siren=holder_siren,
        holder_family_required=True,
        target_holder_family=True,
        subject=subject,
        amount_minor_units=20_000_000,
        currency="eur",
        location=department,
        city="VILLE TEST",
        department=department,
        decision_date=NOW.date(),
        source_url=f"https://www.boamp.fr/avis/{opportunity_key}",
        vertical=(
            "technical_installation"
            if family_key in {"electrical", "insulation"}
            else "general_building"
        ),
        families=((family_key, family_key.replace("_", " ").title()),),
    )


def inventory(
    family_key: str, *signals: AssistedSignal
) -> CatalogFamilyInventory:
    return CatalogFamilyInventory(
        family_key=family_key,
        notices=tuple(CatalogNotice(signal=value) for value in signals),
        mono_notice_count=len(signals),
        missing_official_holder_count=0,
        qualification_error_count=0,
        zero_reason=None if signals else "no_mono_avis",
    )


def seed_supplier(
    engine,
    *,
    siren: str,
    family_key: str,
    department: str,
    employees: int = 20,
) -> None:
    domain = f"supplier-{siren}.example"
    email = f"contact@{domain}"
    with engine.begin() as connection:
        connection.execute(
            sa.insert(supplier_directory).values(
                siren=siren,
                legal_name=f"FOURNISSEUR {siren}",
                legal_name_observed_at=NOW,
                family_keys=[family_key],
                family_review_keys=[],
                family_source="model",
                family_confidence=0.99,
                family_confirmation_status="confirmed",
                families_observed_at=NOW,
                department=department,
                department_observed_at=NOW,
                city="VILLE TEST",
                city_observed_at=NOW,
                employees=employees,
                employees_observed_at=NOW,
                domain=domain,
                website_url=f"https://{domain}",
                domain_source="model",
                domain_confidence=0.99,
                domain_validation_method="model",
                domain_observed_at=NOW,
                directors=[],
                directors_observed_at=NOW,
                professional_email=email,
                email_source="site",
                email_confidence=0.99,
                email_verification_status="mx_verified",
                email_evidence_url=f"https://{domain}/contact",
                email_observed_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def queued_rows(engine, target_ids: tuple[str, ...]) -> tuple[dict[str, object], ...]:
    with engine.connect() as connection:
        by_id = {
            str(row["target_id"]): dict(row)
            for row in connection.execute(sa.select(prospect_target)).mappings()
        }
    return tuple(by_id[target_id] for target_id in target_ids)


def test_catalog_preparation_round_robins_families_before_opening_second_notices(
    migrated_sqlite_engine,
) -> None:
    for siren, family_key, department in (
        ("100000001", "electrical", "38"),
        ("100000002", "electrical", "38"),
        ("100000003", "electrical", "03"),
        ("100000004", "insulation", "26"),
        ("100000005", "insulation", "26"),
    ):
        seed_supplier(
            migrated_sqlite_engine,
            siren=siren,
            family_key=family_key,
            department=department,
        )
    links = Links()
    service = AssistedCatalogPreparationService(
        migrated_sqlite_engine,
        link_issuer=links,
        mail_renderer=render,
        clock=lambda: NOW,
    )

    result = service.prepare(
        {
            "electrical": inventory(
                "electrical",
                signal(
                    "opp-electrical-best",
                    "electrical",
                    department="38",
                    subject="Électricité Stendhal",
                    holder_siren="440055861",
                ),
                signal(
                    "opp-electrical-second",
                    "electrical",
                    department="03",
                    subject="Électricité médiathèque",
                    holder_siren="440055861",
                ),
            ),
            "insulation": inventory(
                "insulation",
                signal(
                    "opp-insulation-best",
                    "insulation",
                    department="26",
                    subject="Isolation école",
                    holder_siren="552100554",
                ),
            ),
        }
    )
    rows = queued_rows(migrated_sqlite_engine, result.target_ids)

    assert result.prepared == 5
    assert [row["family_key"] for row in rows[:4]] == [
        "electrical",
        "insulation",
        "electrical",
        "insulation",
    ]
    assert [row["opportunity_key"] for row in rows] == [
        "opp-electrical-best",
        "opp-insulation-best",
        "opp-electrical-best",
        "opp-insulation-best",
        "opp-electrical-second",
    ]
    assert len(links.calls) == 5


def test_catalog_preparation_is_idempotent_for_active_sirens_and_tokens(
    migrated_sqlite_engine,
) -> None:
    seed_supplier(
        migrated_sqlite_engine,
        siren="100000010",
        family_key="electrical",
        department="38",
    )
    links = Links()
    service = AssistedCatalogPreparationService(
        migrated_sqlite_engine,
        link_issuer=links,
        mail_renderer=render,
        clock=lambda: NOW,
    )
    values = {
        "electrical": inventory(
            "electrical",
            signal(
                "opp-idempotent",
                "electrical",
                department="38",
                subject="Électricité collège",
                holder_siren="440055861",
            ),
        )
    }

    first = service.prepare(values)
    second = service.prepare(values)

    assert first.prepared == 1
    assert second.prepared == 0
    assert second.active_before == 1
    assert second.active_after == 1
    assert len(links.calls) == 1


def test_catalog_preparation_distinguishes_no_site_in_geo_from_history_exclusions(
    migrated_sqlite_engine,
) -> None:
    seed_supplier(
        migrated_sqlite_engine,
        siren="100000020",
        family_key="electrical",
        department="38",
    )
    with migrated_sqlite_engine.begin() as connection:
        connection.execute(
            sa.update(supplier_directory)
            .where(supplier_directory.c.siren == "100000020")
            .values(email_evidence_url=None)
        )
    service = AssistedCatalogPreparationService(
        migrated_sqlite_engine,
        link_issuer=Links(),
        mail_renderer=render,
        clock=lambda: NOW,
    )

    result = service.prepare(
        {
            "electrical": inventory(
                "electrical",
                signal(
                    "opp-no-site",
                    "electrical",
                    department="38",
                    subject="Électricité mairie",
                    holder_siren="440055861",
                ),
            )
        }
    )

    family = result.families[0]
    assert family.queued == 0
    assert family.refused_by_reason == {"non_site_email": 1}
    assert family.zero_reason == "no_site_in_geo"


def test_catalog_preparation_isolates_one_family_qualification_error(
    migrated_sqlite_engine,
) -> None:
    seed_supplier(
        migrated_sqlite_engine,
        siren="100000030",
        family_key="insulation",
        department="26",
    )

    class OneBrokenFamily(AssistedCatalogPreparationService):
        def _qualify_family(self, family_key, *args, **kwargs):
            if family_key == "electrical":
                raise ValueError("private-family-error")
            return super()._qualify_family(family_key, *args, **kwargs)

    service = OneBrokenFamily(
        migrated_sqlite_engine,
        link_issuer=Links(),
        mail_renderer=render,
        clock=lambda: NOW,
    )

    result = service.prepare(
        {
            "electrical": inventory(
                "electrical",
                signal(
                    "opp-broken",
                    "electrical",
                    department="38",
                    subject="Électricité cassée",
                    holder_siren="440055861",
                ),
            ),
            "insulation": inventory(
                "insulation",
                signal(
                    "opp-insulation-safe",
                    "insulation",
                    department="26",
                    subject="Isolation gymnase",
                    holder_siren="552100554",
                ),
            ),
        }
    )

    assert result.prepared == 1
    by_family = {item.family_key: item for item in result.families}
    assert by_family["electrical"].zero_reason == "qualification_error"
    assert by_family["insulation"].queued == 1


def test_catalog_preparation_rolls_back_the_whole_batch_on_render_failure(
    migrated_sqlite_engine,
) -> None:
    seed_supplier(
        migrated_sqlite_engine,
        siren="100000040",
        family_key="electrical",
        department="38",
    )
    seed_supplier(
        migrated_sqlite_engine,
        siren="100000041",
        family_key="insulation",
        department="26",
    )
    calls = 0

    def fail_second(row: dict[str, object]) -> RenderedProspectMail:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("render failed")
        return render(row)

    service = AssistedCatalogPreparationService(
        migrated_sqlite_engine,
        link_issuer=Links(),
        mail_renderer=fail_second,
        clock=lambda: NOW,
    )

    try:
        service.prepare(
            {
                "electrical": inventory(
                    "electrical",
                    signal(
                        "opp-rollback-electric",
                        "electrical",
                        department="38",
                        subject="Électricité école",
                        holder_siren="440055861",
                    ),
                ),
                "insulation": inventory(
                    "insulation",
                    signal(
                        "opp-rollback-insulation",
                        "insulation",
                        department="26",
                        subject="Isolation école",
                        holder_siren="552100554",
                    ),
                ),
            }
        )
    except ValueError as error:
        assert str(error) == "render failed"
    else:
        raise AssertionError("the second render must fail")

    with migrated_sqlite_engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(prospect_target)) == 0
        assert (
            connection.scalar(sa.select(sa.func.count()).select_from(acquisition_runtime_cycle))
            == 0
        )


def test_catalog_rows_keep_their_own_family_opportunity_bait_and_kat1(
    migrated_sqlite_engine,
) -> None:
    seed_supplier(
        migrated_sqlite_engine,
        siren="100000050",
        family_key="electrical",
        department="38",
    )
    service = AssistedCatalogPreparationService(
        migrated_sqlite_engine,
        link_issuer=Links(),
        mail_renderer=render,
        clock=lambda: NOW,
    )

    result = service.prepare(
        {
            "electrical": inventory(
                "electrical",
                signal(
                    "opp-stendhal",
                    "electrical",
                    department="38",
                    subject="Électricité Stendhal",
                    holder_siren="440055861",
                ),
            )
        }
    )
    row = queued_rows(migrated_sqlite_engine, result.target_ids)[0]

    assert row["family_key"] == "electrical"
    assert row["opportunity_key"] == "opp-stendhal"
    assert row["signal_subject"] == "Électricité Stendhal"
    assert row["attribution_payload"]["need_ref"] == "electrical"
    assert row["attribution_payload"]["opportunity_key"] == "opp-stendhal"
    assert row["attribution_url"] in row["mail_text"]
    assert row["attribution_url"] in row["mail_html"]


def test_catalog_cap_counts_active_rows_from_previous_days_and_only_adds_delta(
    migrated_sqlite_engine,
) -> None:
    for index in range(24):
        seed_supplier(
            migrated_sqlite_engine,
            siren=f"{200_000_000 + index:09d}",
            family_key="electrical",
            department="38",
        )
    links = Links()
    service = AssistedCatalogPreparationService(
        migrated_sqlite_engine,
        link_issuer=links,
        mail_renderer=render,
        clock=lambda: NOW,
    )
    values = {
        "electrical": inventory(
            "electrical",
            signal(
                "opp-cap",
                "electrical",
                department="38",
                subject="Électricité lycée",
                holder_siren="440055861",
            ),
        )
    }
    first = service.prepare(values)
    assert first.prepared == 24
    with migrated_sqlite_engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target).values(created_at=NOW - dt.timedelta(days=2))
        )
    seed_supplier(
        migrated_sqlite_engine,
        siren="200000024",
        family_key="electrical",
        department="38",
    )

    second = service.prepare(values)
    third = service.prepare(values)

    assert second.active_before == 24
    assert second.prepared == 1
    assert second.active_after == 25
    assert third.active_before == 25
    assert third.prepared == 0
    assert len(links.calls) == 25


def test_catalog_excludes_holder_rejected_history_and_recent_sent(
    migrated_sqlite_engine,
) -> None:
    for siren in ("300000001", "300000002"):
        seed_supplier(
            migrated_sqlite_engine,
            siren=siren,
            family_key="electrical",
            department="38",
        )
    service = AssistedCatalogPreparationService(
        migrated_sqlite_engine,
        link_issuer=Links(),
        mail_renderer=render,
        clock=lambda: NOW,
    )
    seed_result = service.prepare(
        {
            "electrical": inventory(
                "electrical",
                signal(
                    "opp-exclusion-seed",
                    "electrical",
                    department="38",
                    subject="Électricité initiale",
                    holder_siren="440055861",
                ),
            )
        }
    )
    with migrated_sqlite_engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == seed_result.target_ids[0])
            .values(status="rejected")
        )
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == seed_result.target_ids[1])
            .values(
                status="sent",
                instantly_accepted_at=NOW - dt.timedelta(days=1),
            )
        )
    seed_supplier(
        migrated_sqlite_engine,
        siren="300000003",
        family_key="electrical",
        department="38",
    )
    seed_supplier(
        migrated_sqlite_engine,
        siren="300000004",
        family_key="electrical",
        department="38",
    )

    result = service.prepare(
        {
            "electrical": inventory(
                "electrical",
                signal(
                    "opp-exclusion-final",
                    "electrical",
                    department="38",
                    subject="Électricité finale",
                    holder_siren="300000003",
                ),
            )
        }
    )
    family = result.families[0]
    rows = queued_rows(migrated_sqlite_engine, result.target_ids)

    assert result.prepared == 1
    assert rows[0]["siren"] == "300000004"
    assert family.refused_by_reason == {
        "holder": 1,
        "rejected_history": 1,
        "sent_30j": 1,
    }


def test_catalog_excludes_the_same_historical_target_after_contact_cooldown(
    migrated_sqlite_engine,
) -> None:
    seed_supplier(
        migrated_sqlite_engine,
        siren="310000001",
        family_key="electrical",
        department="38",
    )
    service = AssistedCatalogPreparationService(
        migrated_sqlite_engine,
        link_issuer=Links(),
        mail_renderer=render,
        clock=lambda: NOW,
    )
    values = {
        "electrical": inventory(
            "electrical",
            signal(
                "opp-historical",
                "electrical",
                department="38",
                subject="Électricité historique",
                holder_siren="440055861",
            ),
        )
    }
    first = service.prepare(values)
    with migrated_sqlite_engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == first.target_ids[0])
            .values(
                status="sent",
                instantly_accepted_at=NOW - dt.timedelta(days=31),
            )
        )

    second = service.prepare(values)

    assert second.prepared == 0
    assert second.families[0].refused_by_reason == {"historical_target": 1}


def test_catalog_reports_candidates_deferred_by_the_global_cap(
    migrated_sqlite_engine,
) -> None:
    for index in range(26):
        seed_supplier(
            migrated_sqlite_engine,
            siren=f"{320_000_000 + index:09d}",
            family_key="electrical",
            department="38",
        )
    service = AssistedCatalogPreparationService(
        migrated_sqlite_engine,
        link_issuer=Links(),
        mail_renderer=render,
        clock=lambda: NOW,
    )

    result = service.prepare(
        {
            "electrical": inventory(
                "electrical",
                signal(
                    "opp-deferred",
                    "electrical",
                    department="38",
                    subject="Électricité centre public",
                    holder_siren="440055861",
                ),
            )
        }
    )

    assert result.prepared == 25
    assert result.families[0].eligible == 26
    assert result.families[0].deferred_global_cap == 1


def test_catalog_rejects_a_rendered_mail_with_a_different_kat1_url(
    migrated_sqlite_engine,
) -> None:
    seed_supplier(
        migrated_sqlite_engine,
        siren="330000001",
        family_key="electrical",
        department="38",
    )

    def wrong_url(row: dict[str, object]) -> RenderedProspectMail:
        rendered = render(row)
        return RenderedProspectMail(
            subject=rendered.subject,
            text=rendered.text.replace(
                str(row["attribution_url"]), "https://kivou.eu/a/wrong"
            ),
            html=rendered.html,
            word_count=rendered.word_count,
            contract_status=rendered.contract_status,
            contract_failure=rendered.contract_failure,
        )

    service = AssistedCatalogPreparationService(
        migrated_sqlite_engine,
        link_issuer=Links(),
        mail_renderer=wrong_url,
        clock=lambda: NOW,
    )

    try:
        service.prepare(
            {
                "electrical": inventory(
                    "electrical",
                    signal(
                        "opp-wrong-url",
                        "electrical",
                        department="38",
                        subject="Électricité lien",
                        holder_siren="440055861",
                    ),
                )
            }
        )
    except ValueError as error:
        assert str(error) == "rendered catalog attribution URL mismatch"
    else:
        raise AssertionError("a mismatched kat1 URL must fail the whole batch")
