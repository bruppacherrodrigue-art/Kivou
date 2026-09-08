"""SPEC-009E — acquisition France et mesure des trois sources.

Deux étapes séparées à dessein :

* `acquire()` touche le réseau — API publique Opendatasoft du BOAMP, API DECP de
  `data.economie.gouv.fr`. Elle gèle son résultat sur disque.
* `measure()` ne touche rien : elle relit le gel et produit les chiffres. C'est
  ce qui rend l'étude rejouable et les tests exécutables hors ligne (§39).

La comparaison à trois sources réutilise le banc SPEC-009D pour la Suisse et
l'Union : ses 110 SHOW naturels sont rejoués localement quand les artefacts
gelés de SPEC-009C sont présents, et l'absence est signalée plutôt que comblée.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime as dt
import hashlib
import json
import pathlib
import sys
from typing import Any

from signals.connectors.boamp import (
    BoampClient,
    parse_award_notice,
    supported_payload,
)
from signals.connectors.decp import DECP_DATASET, DECP_LEGACY_DATASET, parse_contract
from signals.france.capacity import (
    LinkageAggregate,
    customer_ready_breakdown,
    unique_contract_count,
)
from signals.france.link import merge_award, resolve_candidates
from signals.recency import assess_recency
from signals.recency.sources import SOURCE_DATE_SEMANTICS
from signals.research.spec009e import (
    as_dict,
    award_facts,
    customer_facing_identity,
    fact_coverage,
    notification_breakdown,
    notification_delay_summary,
    payload_form_counts,
    publication_delay_summary,
    recency_breakdown,
    sample_verdict,
)

FRANCE_DIR = "france"
RAW_FILE = "spec009e_boamp_raw.json"
DECP_RAW_FILE = "spec009e_decp2022_raw.json"
MEASURE_FILE = "spec009e_france.json"
LINKAGE_FILE = "spec009e_r2_linkage.json"

DECP_DATASET_URL = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "decp-2022-marches-valides/records"
)

DEFAULT_WINDOW_DAYS = 90
DEFAULT_MAX_NOTICES = 400


def fixtures_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3] / "tests" / "fixtures"


def france_dir() -> pathlib.Path:
    path = fixtures_root() / FRANCE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ─── acquisition (réseau) ───────────────────────────────────────────────────────


def acquire(
    *,
    as_of: dt.date,
    window_days: int = DEFAULT_WINDOW_DAYS,
    max_notices: int = DEFAULT_MAX_NOTICES,
    out_name: str = RAW_FILE,
) -> dict[str, Any]:
    """Les avis d'attribution BOAMP de la fenêtre, gelés tels quels.

    Le curseur est une date de parution (§38) : la même fenêtre rend la même
    liste, quel que soit le moment de l'appel.
    """
    since = as_of - dt.timedelta(days=window_days)
    with BoampClient() as client:
        records = list(client.fetch_awards_since(since, until=as_of, max_records=max_notices))
    records.sort(key=lambda record: (record.get("dateparution") or "", record.get("idweb") or ""))

    payload = {
        "artefact": "spec009e-boamp-raw",
        "acquired_at": as_of.isoformat(),
        "window": {"since": since.isoformat(), "until": as_of.isoformat()},
        "source": "boamp-datadila.opendatasoft.com dataset=boamp nature=ATTRIBUTION",
        "notices": len(records),
        "records": records,
    }
    target = france_dir() / out_name
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"{len(records)} avis BOAMP gelés dans {target}", file=sys.stderr)
    return payload


def acquire_decp(
    *,
    as_of: dt.date,
    window_days: int = 90,
    max_records: int = 1000,
    out_name: str = DECP_RAW_FILE,
) -> dict[str, Any]:
    """Gèle un échantillon du jeu DECP **courant**, `decp-2022-marches-valides`.

    R1 §1. SPEC-009E avait interrogé `decp-v3-marches-valides` — l'ancien jeu de
    l'arrêté de 2019, figé à février 2024 — et en avait conclu que DECP ne
    pouvait dater aucune victoire récente. Le jeu courant est mis à jour
    quotidiennement ; la conclusion tombe avec la source.
    """
    import httpx

    since = as_of - dt.timedelta(days=window_days)
    where = (
        f"datenotification>=date'{since.isoformat()}' "
        f"and datenotification<=date'{as_of.isoformat()}'"
    )
    records: list[dict] = []
    with httpx.Client(
        timeout=60, headers={"User-Agent": "Kivou/0.1 (award signals; donnees publiques)"}
    ) as client:
        for offset in range(0, max_records, 100):
            response = client.get(
                DECP_DATASET_URL,
                params={
                    "limit": 100,
                    "offset": offset,
                    "where": where,
                    "order_by": "datenotification desc, id asc",
                },
            )
            response.raise_for_status()
            page = response.json().get("results", [])
            records.extend(page)
            if len(page) < 100:
                break
    records.sort(key=lambda record: (record.get("datenotification") or "", str(record.get("id"))))

    payload = {
        "artefact": "spec009e-decp2022-raw",
        "acquired_at": as_of.isoformat(),
        "dataset": DECP_DATASET,
        "window": {"since": since.isoformat(), "until": as_of.isoformat()},
        "records": len(records),
        "rows": records,
    }
    target = france_dir() / out_name
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"{len(records)} contrats DECP gelés dans {target}", file=sys.stderr)
    return payload


def decp_recency_probe(*, as_of: dt.date) -> dict[str, Any]:
    """Compte, côté portail, les contrats notifiés dans chaque fenêtre.

    Interroge les deux jeux — le courant et l'hérité — parce que l'écart entre
    les deux **est** le résultat de R1.
    """
    import httpx

    headers = {"User-Agent": "Kivou/0.1 (award signals; donnees publiques)"}
    base = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
    probe: dict[str, Any] = {}
    with httpx.Client(timeout=60, headers=headers) as client:
        for label, dataset in (("current", DECP_DATASET), ("legacy", DECP_LEGACY_DATASET)):
            url = f"{base}/{dataset}/records"
            entry: dict[str, Any] = {"dataset": dataset}
            response = client.get(url, params={"limit": 0})
            response.raise_for_status()
            entry["total"] = response.json()["total_count"]
            for days in (7, 30, 60, 90, 365):
                since = as_of - dt.timedelta(days=days)
                response = client.get(
                    url,
                    params={
                        "limit": 0,
                        "where": f"datenotification>=date'{since.isoformat()}'",
                    },
                )
                response.raise_for_status()
                entry[f"notified_within_{days}d"] = response.json()["total_count"]
            response = client.get(
                url,
                params={
                    "limit": 1,
                    "where": f"datenotification<=date'{as_of.isoformat()}'",
                    "order_by": "datenotification desc",
                    "select": "datenotification",
                },
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            entry["most_recent_notification"] = results[0]["datenotification"] if results else None
            probe[label] = entry
    return probe


def linkage_sweep(
    *,
    as_of: dt.date,
    raw_name: str = RAW_FILE,
    out_name: str = LINKAGE_FILE,
    only_recent_awards: bool = True,
) -> dict[str, Any]:
    """Interroge DECP pour chaque award-lot BOAMP testable, et gèle le bilan.

    R2 §3, §4. C'est la seule façon honnête de savoir si « 45 attributions » et
    « 383 notifications » décrivent 428 marchés ou nettement moins.

    Un award-lot n'est **testable** que s'il porte à la fois le SIRET de
    l'acheteur et celui du titulaire : ce sont les deux seules clés que les deux
    registres partagent. Les autres ne sont pas « non appariés », ils sont
    **non testés**, et l'encadrement de `unique_contract_count` repose entièrement
    sur cette distinction.
    """
    import httpx

    raw = json.loads((france_dir() / raw_name).read_text(encoding="utf-8"))
    tested: list[dict[str, Any]] = []
    linkable = 0
    returned = 0
    outcomes: collections.Counter[str] = collections.Counter()
    conflicts = 0
    decoys = 0
    agreement: collections.Counter[str] = collections.Counter()

    with httpx.Client(
        timeout=60, headers={"User-Agent": "Kivou/0.1 (award signals; donnees publiques)"}
    ) as client:
        for record in raw["records"]:
            if not supported_payload(record):
                continue
            event, awards = parse_award_notice(record)
            published = event.published_at
            publication_date = published.date() if isinstance(published, dt.datetime) else published
            buyers = {
                identifier.value
                for organization in event.procedure_buyers
                for identifier in organization.identifiers
                if identifier.scheme == "SIRET"
            }
            for award in awards:
                recency = assess_recency(
                    award_date=award.award_date,
                    publication_date=publication_date,
                    as_of=as_of,
                )
                if only_recent_awards and not recency.award_clock.is_recent:
                    continue
                winners = {
                    identifier.value
                    for party in award.awardee_parties
                    for member in party.members
                    for identifier in member.organization.identifiers
                    if identifier.scheme == "SIRET"
                }
                entry: dict[str, Any] = {
                    "notice": record["idweb"],
                    "contract": award.source_award_id,
                    "award_date": award.award_date.isoformat() if award.award_date else None,
                    "winner_named": bool(
                        [member for party in award.awardee_parties for member in party.members]
                    ),
                }
                if not buyers or not winners:
                    entry["outcome"] = "not_linkable"
                    tested.append(entry)
                    continue

                linkable += 1
                # Déterministe : le plus petit SIRET, jamais l'ordre d'itération d'un set.
                buyer = min(buyers)
                winner = min(winners)
                response = client.get(
                    DECP_DATASET_URL,
                    params={
                        "limit": 20,
                        "where": f'acheteur_id="{buyer}" and titulaire_id_1="{winner}"',
                    },
                )
                response.raise_for_status()
                rows = response.json().get("results", [])
                returned += len(rows)
                candidates = resolve_candidates(award, event, rows)
                best = candidates[0] if candidates else None
                strength = best.strength if best else "unresolved"
                outcomes[strength] += 1
                entry["outcome"] = strength
                entry["decp_returned"] = len(rows)
                if best is not None and strength == "strong":
                    entry["decp_id"] = best.decp_id
                    entry["matched_on"] = list(best.matched_on)
                    entry["diverged_on"] = list(best.diverged_on)
                    for field in ("cpv", "amount", "contract_reference"):
                        if field in best.matched_on:
                            agreement[field] += 1
                    match = next(row for row in rows if str(row.get("id")) == best.decp_id)
                    merged = merge_award(award, match)
                    if merged.conflicts:
                        conflicts += 1
                        entry["conflicts"] = [conflict.field for conflict in merged.conflicts]
                decoys += sum(
                    1
                    for candidate in candidates
                    if candidate.strength == "unresolved" and candidate.matched_on
                )
                tested.append(entry)

    payload = {
        "artefact": "spec009e-r2-linkage",
        "as_of": as_of.isoformat(),
        "window": raw["window"],
        "scope": "award-lots BOAMP dont la décision est récente (≤ 30 j)"
        if only_recent_awards
        else "tous les award-lots BOAMP de la fenêtre",
        "boamp_candidates_tested": len(tested),
        "boamp_linkable": linkable,
        "decp_candidates_returned": returned,
        "strong": outcomes["strong"],
        "probable": outcomes["probable"],
        "unresolved": outcomes["unresolved"],
        "conflicts": conflicts,
        "decoys_rejected": decoys,
        "strong_link_agreement": dict(agreement),
        "entries": tested,
    }
    target = france_dir() / out_name
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"rapprochement : {len(tested)} testés, {linkable} testables, {outcomes['strong']} forts",
        file=sys.stderr,
    )
    return payload


# ─── mesure (hors ligne) ────────────────────────────────────────────────────────


def measure(
    *,
    as_of: dt.date,
    raw_name: str = RAW_FILE,
    decp_probe: dict[str, Any] | None = None,
    out_name: str = MEASURE_FILE,
) -> dict[str, Any]:
    """Relit le gel BOAMP et produit toute la partie France du rapport."""
    # Une re-mesure sans réseau ne doit pas effacer le recensement déjà obtenu :
    # sans lui, le volume hebdomadaire de §6.B redeviendrait indisponible.
    measured_path = france_dir() / out_name
    if decp_probe is None and measured_path.exists():
        decp_probe = json.loads(measured_path.read_text(encoding="utf-8")).get("decp_probe")

    raw_path = france_dir() / raw_name
    raw_text = raw_path.read_text(encoding="utf-8")
    raw = json.loads(raw_text)
    records = raw["records"]

    forms = payload_form_counts(records)
    sample = []
    parse_failures: list[str] = []
    for record in records:
        if not supported_payload(record):
            continue
        try:
            event, awards = parse_award_notice(record)
        except Exception as error:  # noqa: BLE001 — un échec est une mesure, pas un crash
            parse_failures.append(f"{record.get('idweb')}: {error}")
            continue
        for award in awards:
            sample.append(award_facts(event, award, source="boamp"))

    decp_sample: list[Any] = []
    decp_path = france_dir() / DECP_RAW_FILE
    decp_raw: dict[str, Any] | None = None
    if decp_path.exists():
        decp_text = decp_path.read_text(encoding="utf-8")
        decp_raw = json.loads(decp_text)
        for row in decp_raw["rows"]:
            event, contract = parse_contract(row)
            decp_sample.append(award_facts(event, contract, source="decp"))

    payload: dict[str, Any] = {
        "artefact": "spec009e-france",
        "revision": "R1",
        "as_of": as_of.isoformat(),
        "inputs": {
            "raw_file": raw_name,
            "raw_sha256": _sha256(raw_text),
            "window": raw["window"],
            "notices_acquired": raw["notices"],
        },
        "payload_forms": forms,
        "eforms_share_pct": (
            round(100 * forms.get("EFORMS", 0) / sum(forms.values()), 1) if forms else None
        ),
        "parse_failures": parse_failures,
        "sample": {
            "notices_parsed": forms.get("EFORMS", 0),
            "award_lots": len(sample),
            "verdict": sample_verdict(len(sample)),
        },
        "fact_coverage": fact_coverage(sample),
        "recency": recency_breakdown(sample, as_of=as_of),
        "publication_delay": publication_delay_summary(sample),
        "date_semantics": {source: SOURCE_DATE_SEMANTICS[source] for source in ("boamp", "decp")},
        "customer_facing_identity": customer_facing_identity(sample),
        "decp": {
            "dataset": DECP_DATASET,
            "legacy_dataset_not_used": DECP_LEGACY_DATASET,
            "raw_file": DECP_RAW_FILE if decp_raw else None,
            "raw_sha256": _sha256(decp_text) if decp_raw else None,
            "window": decp_raw["window"] if decp_raw else None,
            "contracts": len(decp_sample),
            "fact_coverage": fact_coverage(decp_sample),
            "notification": notification_breakdown(decp_sample, as_of=as_of),
            "notification_to_publication_delay": notification_delay_summary(decp_sample),
            "recency": recency_breakdown(decp_sample, as_of=as_of),
            "customer_facing_identity": customer_facing_identity(decp_sample),
        },
        "decp_probe": decp_probe,
        "award_lots": [as_dict(facts) for facts in sample],
    }
    payload["three_source_comparison"] = three_source_comparison(payload, as_of=as_of)
    linkage_path = france_dir() / LINKAGE_FILE
    linkage = (
        json.loads(linkage_path.read_text(encoding="utf-8")) if linkage_path.exists() else None
    )
    payload["france_capacity"] = france_capacity(payload, linkage)
    if linkage is not None:
        payload["france_capacity"]["linkage_sha256"] = _sha256(
            linkage_path.read_text(encoding="utf-8")
        )

    target = france_dir() / out_name
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"mesure France écrite dans {target}", file=sys.stderr)
    return payload


def swiss_and_eu_recency(*, as_of: dt.date) -> dict[str, Any] | None:
    """Rejoue les 110 SHOW de SPEC-009D pour situer la France par rapport à eux.

    Rend `None` quand les artefacts gelés SPEC-009C sont absents : une comparaison
    fabriquée serait pire qu'une comparaison manquante.
    """
    corpus = fixtures_root() / "signal100" / "spec009c_corpus.json"
    bench = fixtures_root() / "signal100" / "spec009c_bench.json"
    if not corpus.exists() or not bench.exists():
        return None

    from signals.matching.reference import CONSTRUCTION_INPUTS_ICP
    from signals.research.signal100 import load_rows
    from signals.research.signal100_pipeline import run_pipeline

    per_source: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    delays: dict[str, list[int]] = collections.defaultdict(list)
    for run in run_pipeline(load_rows(corpus), as_of=as_of, icps=(CONSTRUCTION_INPUTS_ICP,)):
        for match in run.matches:
            if match.decision != "show":
                continue
            timing = run.understanding.timing
            published = timing.published_at
            publication_date = published.date() if isinstance(published, dt.datetime) else published
            recency = assess_recency(
                award_date=timing.award_date,
                publication_date=publication_date,
                as_of=as_of,
            )
            per_source[run.lot.source][recency.status] += 1
            if recency.publication_delay_days is not None and recency.is_datable:
                delays[run.lot.source].append(recency.publication_delay_days)

    from signals.research.spec009e import _summary

    return {
        source: {
            "n": sum(counts.values()),
            "statuses": dict(counts),
            "recent_award_pct": round(100 * counts["recent_award"] / sum(counts.values()), 1),
            "publication_delay": _summary(delays[source]),
        }
        for source, counts in sorted(per_source.items())
    }


def three_source_comparison(france: dict[str, Any], *, as_of: dt.date) -> dict[str, Any]:
    """SIMAP, TED, BOAMP, DECP — la même mesure, côte à côte (R1 §6).

    Quatre lignes et non trois : la décision d'attribution et la notification du
    contrat sont deux actes distincts, et R1 §6 interdit explicitement de les
    fondre dans une métrique unique. BOAMP porte la première, DECP la seconde.
    """
    comparison: dict[str, Any] = {
        "france_boamp_award_decision": {
            "measures": "décision d'attribution (BT-1451)",
            "n": france["recency"]["n"],
            "statuses": france["recency"]["statuses"],
            "recent_award_pct": france["recency"]["recent_award_pct"],
            "publication_delay": france["publication_delay"],
            "award_date_coverage_pct": france["fact_coverage"]["award_date"]["known_pct"],
        }
    }
    decp = france.get("decp") or {}
    if decp.get("contracts"):
        comparison["france_decp_contract_notification"] = {
            "measures": "notification du contrat (dateNotification)",
            "n": decp["contracts"],
            "statuses": decp["recency"]["statuses"],
            "award_date_coverage_pct": decp["fact_coverage"]["award_date"]["known_pct"],
            "notification_coverage_pct": decp["notification"]["known_pct"],
            "notified_within": decp["notification"]["within"],
            "notification_to_publication_delay": decp["notification_to_publication_delay"],
        }

    others = swiss_and_eu_recency(as_of=as_of)
    if others is None:
        comparison["note"] = (
            "artefacts gelés SPEC-009C absents : Suisse et Union non recalculées ici"
        )
        return comparison
    for source, values in others.items():
        comparison[source] = values | {
            "measures": "décision d'attribution",
            "award_date_coverage_pct": (
                round(
                    100
                    * sum(
                        values["statuses"].get(status, 0)
                        for status in ("recent_award", "aging_award", "stale_award")
                    )
                    / values["n"],
                    1,
                )
                if values["n"]
                else None
            ),
        }
    return comparison


def france_capacity(france: dict[str, Any], linkage: dict[str, Any] | None) -> dict[str, Any]:
    """R2 §3, §5, §6 — les trois nombres, et rien entre les bornes.

    R1 avait additionné 45 attributions récentes et 383 notifications récentes
    pour annoncer 428 opportunités hebdomadaires. Deux registres qui décrivent
    parfois le même marché ne s'additionnent pas : la somme est un plafond, pas
    une mesure.
    """
    probe = (france.get("decp_probe") or {}).get("current") or {}
    boamp_window = france["inputs"]["window"]
    since = dt.date.fromisoformat(boamp_window["since"])
    until = dt.date.fromisoformat(boamp_window["until"])
    days = max((until - since).days, 1)

    raw_boamp = round(france["recency"]["statuses"].get("recent_award", 0) * 7 / days)
    raw_decp = probe.get("notified_within_7d")

    capacity: dict[str, Any] = {
        "A_raw_public_events_per_week": {
            "boamp_recent_award_decisions": raw_boamp,
            "boamp_basis": f"fenêtre observée de {days} jours, non plafonnée",
            "decp_recent_contract_notifications": raw_decp,
            "decp_basis": "recensement portail sur les 7 derniers jours",
            "naive_sum": (raw_boamp + raw_decp) if raw_decp is not None else None,
            "warning": (
                "cette somme n'est PAS un nombre d'opportunités : les deux "
                "registres décrivent parfois le même marché (R2 §3)"
            ),
        }
    }
    if linkage is None or raw_decp is None:
        capacity["B_unique_contract_opportunities_per_week"] = {
            "status": "non mesurable — passe de rapprochement absente"
        }
        capacity["C_customer_ready_opportunities_per_week"] = {"status": "non mesurable"}
        return capacity

    aggregate = LinkageAggregate(
        boamp_candidates_tested=linkage["boamp_candidates_tested"],
        boamp_linkable=linkage["boamp_linkable"],
        decp_candidates_returned=linkage["decp_candidates_returned"],
        strong=linkage["strong"],
        probable=linkage["probable"],
        unresolved=linkage["unresolved"],
        conflicts=linkage["conflicts"],
        decoys_rejected=linkage["decoys_rejected"],
    )
    unique = unique_contract_count(raw_boamp=raw_boamp, raw_decp=raw_decp, linkage=aggregate)
    capacity["linkage_aggregate"] = dataclasses.asdict(aggregate) | {
        "boamp_not_linkable": aggregate.boamp_not_linkable,
        "strong_rate_over_linkable": aggregate.strong_rate_over_linkable,
        "strong_rate_over_tested": aggregate.strong_rate_over_tested,
        "strong_link_agreement": linkage.get("strong_link_agreement"),
        "scope": linkage.get("scope"),
        "direction": (
            "BOAMP → DECP uniquement : l'API du BOAMP n'est pas interrogeable par "
            "SIRET, le sens inverse n'est donc pas mesurable"
        ),
    }
    capacity["B_unique_contract_opportunities_per_week"] = dataclasses.asdict(unique) | {
        "raw_sum": unique.raw_sum
    }

    # C — un nom affichable, pas seulement un identifiant stable.
    named_boamp = sum(1 for entry in linkage["entries"] if entry.get("winner_named"))
    boamp_identity = customer_ready_breakdown(
        named=named_boamp,
        identified=aggregate.boamp_linkable,
        named_and_identified=aggregate.boamp_linkable,
        name_recovered_via_link=0,
        total=linkage["boamp_candidates_tested"],
    )
    decp_identity = customer_ready_breakdown(
        named=0,
        identified=raw_decp,
        named_and_identified=0,
        name_recovered_via_link=aggregate.strong,
        total=raw_decp,
    )
    capacity["C_customer_ready_opportunities_per_week"] = {
        "boamp": dataclasses.asdict(boamp_identity),
        "decp": dataclasses.asdict(decp_identity),
        "measured_lower_bound": boamp_identity.customer_ready,
        "note": (
            "les noms récupérés côté DECP le sont via un lien fort vers un avis "
            "BOAMP déjà compté : ils ne s'ajoutent pas. La borne haute dépend des "
            "liens DECP → BOAMP non mesurables (§4)."
        ),
    }
    return capacity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SPEC-009E — étude France")
    parser.add_argument("--as-of", default=dt.datetime.now(tz=dt.UTC).date().isoformat())
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--max-notices", type=int, default=DEFAULT_MAX_NOTICES)
    parser.add_argument("--skip-acquire", action="store_true", help="mesurer un gel existant")
    args = parser.parse_args(argv)
    as_of = dt.date.fromisoformat(args.as_of)

    probe = None
    if not args.skip_acquire:
        acquire(as_of=as_of, window_days=args.window_days, max_notices=args.max_notices)
        acquire_decp(as_of=as_of)
        probe = decp_recency_probe(as_of=as_of)
        linkage_sweep(as_of=as_of)
    payload = measure(as_of=as_of, decp_probe=probe)
    print(
        json.dumps(
            {
                "award_lots": payload["sample"]["award_lots"],
                "recent_award_pct": payload["recency"]["recent_award_pct"],
                "verdict": payload["sample"]["verdict"],
                "capacity": payload["france_capacity"].get(
                    "B_unique_contract_opportunities_per_week"
                ),
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
