"""One official-holder cache shared by acquisition mail and customer feed."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable

import sqlalchemy as sa

from signals.companies.schema import saas_company
from signals.persistence.schema import materialized_signal


@dataclasses.dataclass(frozen=True)
class OfficialHolder:
    name: str
    country: str | None
    identifier_scheme: str | None
    identifier_value: str | None
    source_award_key: str


def official_holders_for_opportunities(
    connection: sa.Connection, opportunity_keys: Iterable[str]
) -> dict[str, OfficialHolder]:
    """Read the newest official-register identity for each opportunity."""

    keys = tuple(sorted(set(opportunity_keys)))
    if not keys:
        return {}
    rows = connection.execute(
        sa.select(
            materialized_signal.c.opportunity_key,
            saas_company.c.official_name,
            saas_company.c.official_country,
            saas_company.c.official_identifiers,
            saas_company.c.source_award_key,
        )
        .select_from(
            materialized_signal.join(
                saas_company,
                saas_company.c.identity_fingerprint
                == materialized_signal.c.company_identity_fingerprint,
            )
        )
        .where(
            materialized_signal.c.opportunity_key.in_(keys),
            saas_company.c.official_source == "official_register",
            sa.func.nullif(
                sa.func.trim(sa.func.coalesce(saas_company.c.official_name, "")), ""
            ).isnot(None),
        )
        .order_by(
            materialized_signal.c.opportunity_key,
            saas_company.c.official_observed_at.desc(),
            saas_company.c.company_key,
        )
    ).mappings()
    resolved: dict[str, OfficialHolder] = {}
    for row in rows:
        name = str(row["official_name"]).strip()
        if not any(character.isalpha() for character in name):
            continue
        identifiers = row["official_identifiers"] or []
        first = next((item for item in identifiers if isinstance(item, dict)), None)
        resolved.setdefault(
            str(row["opportunity_key"]),
            OfficialHolder(
                name=name,
                country=row["official_country"],
                identifier_scheme=None if first is None else first.get("scheme"),
                identifier_value=None if first is None else first.get("value"),
                source_award_key=str(row["source_award_key"]),
            ),
        )
    return resolved


__all__ = ["OfficialHolder", "official_holders_for_opportunities"]
