"""Smoke test live TED — volontaire, jamais lancé par la suite de tests.

    uv run python -m signals.connectors.ted.live_smoke --days 10 --limit 25

Appelle l'API réelle, télécharge les XML, les traduit en faits canoniques et
imprime les statistiques d'extraction. En cas d'indisponibilité de TED, sort en
erreur avec un message lisible — pas de trace obscure, pas de réessai en boucle.

`--json chemin` écrit le détail par notice (pour une revue manuelle ligne à ligne).
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
import time
from dataclasses import dataclass, field

from signals.connectors.ted.client import TedClient
from signals.connectors.ted.errors import TedError
from signals.connectors.ted.mapping import map_notice
from signals.connectors.ted.parser import parse_notice

# `form-type=result` couvre tous les avis d'attribution (can-standard, can-social,
# can-desg…). Le tri décroissant donne les plus récents publiés.
QUERY = "form-type=result AND publication-date>=today(-{days}) SORT BY publication-number DESC"


@dataclass
class Metrics:
    """Ce que l'échantillon dit des données, pas seulement du code."""

    notices_fetched: int = 0
    notices_parsed: int = 0
    notices_failed: int = 0
    contracts_produced: int = 0
    winner_identified: int = 0
    winner_ambiguous: int = 0
    winner_undisclosed: int = 0
    awards_without_value: int = 0
    multi_lot_notices: int = 0
    multi_contract_notices: int = 0
    consortium_cases: int = 0
    multi_party_awards: int = 0
    notices_with_joint_buyers: int = 0
    awards_with_signatory: int = 0
    awards_with_contract_reference: int = 0
    awards_without_contract_reference: int = 0
    notices_with_procedure_id: int = 0
    framework_cases: int = 0
    lots_not_awarded: int = 0
    warnings: collections.Counter = field(default_factory=collections.Counter)
    failures: list[str] = field(default_factory=list)
    # publication numbers groupés par identifiant de procédure (BT-04). Un même
    # marché publie souvent plusieurs avis : compter les avis n'est PAS compter
    # les procédures, et confondre les deux produit des chiffres incohérents.
    procedures: collections.defaultdict = field(
        default_factory=lambda: collections.defaultdict(list)
    )

    @property
    def unique_procedure_ids(self) -> int:
        return len(self.procedures)

    def procedure_groups(self) -> dict[str, list[str]]:
        """Procédures couvertes par plus d'un avis de l'échantillon."""
        return {k: v for k, v in self.procedures.items() if len(v) > 1}

    def as_dict(self) -> dict[str, object]:
        skip = ("warnings", "failures", "procedures")
        data = {k: v for k, v in self.__dict__.items() if k not in skip}
        data["unique_procedure_ids"] = self.unique_procedure_ids
        data["procedure_groups_with_several_notices"] = self.procedure_groups()
        data["warnings"] = dict(self.warnings)
        data["failures"] = self.failures
        return data


def run(days: int, limit: int, pause: float, json_path: str | None) -> Metrics:
    metrics = Metrics()
    per_notice: list[dict[str, object]] = []

    with TedClient() as client:
        refs = client.search_all(QUERY.format(days=days), wanted=limit, page_size=min(limit, 50))
        print(f"{len(refs)} notices trouvées sur TED (fenêtre {days} jours)", file=sys.stderr)

        for index, ref in enumerate(refs, start=1):
            metrics.notices_fetched += 1
            try:
                xml = client.fetch_notice_xml(ref.publication_number)
                notice = parse_notice(xml)
                result = map_notice(notice, retrieved_at=dt.datetime.now(dt.UTC))
            except TedError as exc:
                metrics.notices_failed += 1
                metrics.failures.append(f"{ref.publication_number}: {exc}")
                print(f"[{index}/{len(refs)}] {ref.publication_number} ÉCHEC — {exc}")
                continue

            metrics.notices_parsed += 1
            metrics.contracts_produced += len(result.awards)
            metrics.lots_not_awarded += result.lots_not_awarded
            metrics.multi_lot_notices += result.lots > 1
            metrics.multi_contract_notices += len(result.awards) > 1
            metrics.framework_cases += any(c.framework for c in notice.contracts)
            procedure_id = result.event.provenance.source_procedure_id
            metrics.notices_with_procedure_id += procedure_id is not None
            if procedure_id:
                metrics.procedures[procedure_id].append(ref.publication_number)
            metrics.notices_with_joint_buyers += len(result.event.procedure_buyers) > 1
            for award in result.awards:
                metrics.winner_identified += award.winner_status == "identified"
                metrics.winner_ambiguous += award.winner_status == "ambiguous"
                metrics.winner_undisclosed += award.winner_status == "undisclosed"
                metrics.awards_without_value += award.value is None
                metrics.awards_with_signatory += bool(award.contract_signatories)
                metrics.consortium_cases += any(p.is_group for p in award.awardee_parties)
                metrics.multi_party_awards += len(award.awardee_parties) > 1
                metrics.awards_with_contract_reference += award.contract_reference is not None
                metrics.awards_without_contract_reference += award.contract_reference is None
            for warning in result.warnings:
                metrics.warnings[warning.code] += 1

            print(
                f"[{index}/{len(refs)}] {ref.publication_number} {ref.buyer_country or '??'} "
                f"lots={result.lots} contrats={len(result.awards)} "
                f"infructueux={result.lots_not_awarded} "
                f"avertissements={len(result.warnings)}"
            )
            per_notice.append(_detail(ref, notice, result))
            time.sleep(pause)

    if json_path:
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(
                {"metrics": metrics.as_dict(), "notices": per_notice},
                handle,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        print(f"détail écrit dans {json_path}", file=sys.stderr)
    return metrics


def _detail(ref: object, notice: object, result: object) -> dict[str, object]:
    return {
        "publication_number": ref.publication_number,
        "notice_uuid": notice.notice_uuid,
        "notice_version": notice.version,
        "procedure_id": notice.procedure_id,
        "notice_type": notice.notice_type,
        "buyer_country": ref.buyer_country,
        "published_at": str(result.event.published_at),
        "procedure_buyers": [b.legal_name for b in result.event.procedure_buyers],
        "lots": result.lots,
        "lot_results": result.lot_results,
        "lots_not_awarded": result.lots_not_awarded,
        "contracts": result.contracts,
        "warnings": [str(w) for w in result.warnings],
        "awards": [
            {
                "source_award_id": a.source_award_id,
                "lot": a.lot.identifier if a.lot else None,
                "contract_signatories": [x.legal_name for x in a.contract_signatories],
                "parties": [
                    {"name": p.name, "members": [m.organization.legal_name for m in p.members]}
                    for p in a.awardee_parties
                ],
                "contract_reference": a.contract_reference,
                "winner_status": a.winner_status,
                "value": f"{a.value.canonical_amount()} {a.value.currency}" if a.value else None,
                "cpv_main": a.cpv_main.code if a.cpv_main else None,
                "award_date": str(a.award_date) if a.award_date else None,
                "signature_date": str(a.contract_signature_date)
                if a.contract_signature_date
                else None,
                "identity": a.source_identity().model_dump() if a.source_identity() else None,
            }
            for a in result.awards
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test live du connecteur TED")
    parser.add_argument("--days", type=int, default=10, help="fenêtre de publication en jours")
    parser.add_argument("--limit", type=int, default=25, help="nombre de notices à traiter")
    parser.add_argument("--pause", type=float, default=0.6, help="pause entre requêtes (s)")
    parser.add_argument("--json", dest="json_path", default=None, help="fichier de détail")
    args = parser.parse_args()

    try:
        metrics = run(args.days, args.limit, args.pause, args.json_path)
    except TedError as exc:
        print(f"TED indisponible : {exc}", file=sys.stderr)
        return 2

    print("\n─── MÉTRIQUES ───")
    reported = metrics.as_dict()
    groups = reported.pop("procedure_groups_with_several_notices")
    for key, value in reported.items():
        if key not in ("warnings", "failures"):
            print(f"{key:34} {value}")
    print(f"{'procedure groups > 1 notice':34} {groups or '—'}")
    print(f"{'warnings':34} {dict(metrics.warnings) or '—'}")
    if metrics.failures:
        print(f"{'failures':34} {metrics.failures}")
    return 1 if metrics.notices_parsed == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
