"""`GET /signals/filters` — les valeurs de filtre RÉELLEMENT présentes.

Le sélecteur d'un filtre (zone, secteur) ne doit pas proposer la nomenclature
entière — des milliers d'entrées CPV, tous les départements français — mais
seulement ce que le compte peut effectivement voir dans ses signaux
accessibles. La portée est donc EXACTEMENT celle de `list_companies`
(`companies/listing.py`) : le même balayage borné, `_ownership_scoped` +
`allowed_target_icp_ids` + `FeedAccess.is_unlocked`, plafonné par
`HISTORY_SCAN_CAP` et annoncé tronqué de la même façon plutôt que
silencieusement coupé.

Un compte dont le plan ne couvre pas un filtre (`filter_is_available`) reçoit
quand même une réponse 200 — la liste correspondante est simplement vide : le
client sait déjà griser le contrôle via `filter_access`, il n'a pas besoin
d'un autre code pour ça.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.billing.access import FeedAccess, filter_is_available
from signals.companies.listing import _scan_accessible_signals
from signals.domain.cpv_labels import cpv_label
from signals.domain.subdivisions import subdivision_label
from signals.feed.french_departments import location_subdivision


@dataclasses.dataclass(frozen=True)
class SubdivisionEntry:
    code: str
    label: str
    country: str


@dataclasses.dataclass(frozen=True)
class SectorEntry:
    prefix: str
    label: str


@dataclasses.dataclass(frozen=True)
class AvailableFilters:
    subdivisions: tuple[SubdivisionEntry, ...]
    sectors: tuple[SectorEntry, ...]
    scan_truncated: bool


def available_filters(
    connection: sa.Connection,
    *,
    account_id: str,
    as_of: dt.date,
    allowed_target_icp_ids: frozenset[str] | None,
    access: FeedAccess,
    lang: str,
) -> AvailableFilters:
    """Les subdivisions et secteurs des signaux accessibles, avec doublons fusionnés.

    Triés alphabétiquement par libellé ; une entrée sans libellé (subdivision
    ou code CPV que la nomenclature ne couvre pas) est exclue plutôt que
    montrée vide.
    """
    signals, scan_truncated = _scan_accessible_signals(
        connection,
        account_id=account_id,
        as_of=as_of,
        allowed_target_icp_ids=allowed_target_icp_ids,
        access=access,
    )

    subdivisions: dict[str, SubdivisionEntry] = {}
    sectors: dict[str, SectorEntry] = {}
    for signal in signals:
        code = location_subdivision(signal.award.place_of_performance)
        if code is not None and code not in subdivisions:
            label = subdivision_label(code)
            if label is not None:
                country = code.split("-", 1)[0]
                subdivisions[code] = SubdivisionEntry(code=code, label=label, country=country)

        cpv_main = signal.award.cpv_main
        if cpv_main:
            prefix = cpv_main[:2]
            if len(prefix) == 2 and prefix not in sectors:
                label = cpv_label(prefix + "000000", lang=lang)
                if label is not None:
                    sectors[prefix] = SectorEntry(prefix=prefix, label=label)

    subdivision_available = filter_is_available(access.entitlements, "subdivision_code")
    sector_available = filter_is_available(access.entitlements, "cpv_prefix")

    return AvailableFilters(
        subdivisions=(
            tuple(sorted(subdivisions.values(), key=lambda entry: entry.label))
            if subdivision_available
            else ()
        ),
        sectors=(
            tuple(sorted(sectors.values(), key=lambda entry: entry.label))
            if sector_available
            else ()
        ),
        scan_truncated=scan_truncated,
    )


__all__ = ["AvailableFilters", "SectorEntry", "SubdivisionEntry", "available_filters"]
