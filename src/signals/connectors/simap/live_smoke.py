"""Smoke test live SIMAP — volontaire, jamais lancé par la suite de tests.

    uv run python -m signals.connectors.simap.live_smoke --limit 25 --since 2026-07-01

Appelle l'API publique réelle, traduit les publications en faits canoniques et
imprime les statistiques d'extraction. `--link` va en plus chercher la
publication d'appel d'offres d'origine, uniquement pour mesurer la disponibilité
des documents — **aucun document n'est téléchargé**, et les points d'accès
documentaires exigent de toute façon un rôle acheteur ou soumissionnaire.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
import time
from dataclasses import dataclass, field

from signals.connectors.simap.client import SimapClient
from signals.connectors.simap.errors import SimapAuthRequiredError, SimapError
from signals.connectors.simap.mapping import map_publication
from signals.connectors.simap.parser import parse_publication


@dataclass
class Metrics:
    """Ce que l'échantillon dit des données, pas seulement du code."""

    projects_fetched: int = 0
    award_publications_fetched: int = 0
    award_publications_parsed: int = 0
    failed: int = 0
    contracts_produced: int = 0

    identified_winners: int = 0
    ambiguous_winners: int = 0
    awards_without_winner: int = 0
    awards_without_value: int = 0

    single_lot_publications: int = 0
    publications_with_lot: int = 0
    multi_contract_publications: int = 0
    consortium_cases: int = 0
    multi_party_independent: int = 0

    publications_with_several_buyers: int = 0

    awards_with_referencing_pub: int = 0
    awards_without_referencing_pub: int = 0

    awards_with_source_procedure_id: int = 0
    awards_with_contract_reference: int = 0

    publications_with_project_documents: int = 0
    linked_original_tenders: int = 0
    original_tenders_with_project_documents: int = 0
    anonymous_document_access_observed: int = 0
    auth_required_document_access_observed: int = 0

    not_contract_awards: int = 0
    # Régime de TVA publié avec chaque montant retenu. `unspecified` = la source
    # ne le dit pas ; ce n'est pas « pas de TVA ».
    vat_categories: collections.Counter = field(default_factory=collections.Counter)
    warnings: collections.Counter = field(default_factory=collections.Counter)
    failures: list[str] = field(default_factory=list)
    procedures: collections.defaultdict = field(
        default_factory=lambda: collections.defaultdict(list)
    )

    @property
    def unique_procedures(self) -> int:
        return len(self.procedures)

    def as_dict(self) -> dict[str, object]:
        skip = ("warnings", "failures", "procedures", "vat_categories")
        data = {k: v for k, v in self.__dict__.items() if k not in skip}
        data["unique_procedures"] = self.unique_procedures
        data["vat_categories"] = dict(self.vat_categories)
        data["warnings"] = dict(self.warnings)
        data["failures"] = self.failures
        return data


def run(limit: int, since: str, pause: float, link: bool, json_path: str | None) -> Metrics:
    metrics = Metrics()
    detail: list[dict[str, object]] = []

    with SimapClient() as client:
        refs = client.search_all_awards(wanted=limit, published_from=since)
        metrics.projects_fetched = len(refs)
        print(f"{len(refs)} projets d'adjudication trouvés (depuis {since})", file=sys.stderr)

        for index, ref in enumerate(refs, start=1):
            metrics.award_publications_fetched += 1
            try:
                payload = client.fetch_publication(ref.project_id, ref.publication_id)
                publication = parse_publication(payload, search_entry=ref.search_entry)
                result = map_publication(publication, retrieved_at=dt.datetime.now(dt.UTC))
            except SimapError as exc:
                metrics.failed += 1
                metrics.failures.append(f"{ref.publication_number}: {exc}")
                print(f"[{index}/{len(refs)}] {ref.publication_number} ÉCHEC — {exc}")
                continue

            metrics.award_publications_parsed += 1
            metrics.contracts_produced += len(result.awards)
            metrics.procedures[publication.project_id].append(publication.publication_number)
            metrics.publications_with_lot += result.has_lot
            metrics.single_lot_publications += not result.has_lot
            metrics.multi_contract_publications += len(result.awards) > 1
            metrics.publications_with_several_buyers += len(result.event.procedure_buyers) > 1
            metrics.publications_with_project_documents += result.has_project_documents
            metrics.not_contract_awards += any(
                w.code == "not-a-contract-award" for w in result.warnings
            )

            for award in result.awards:
                metrics.identified_winners += award.winner_status == "identified"
                metrics.ambiguous_winners += award.winner_status == "ambiguous"
                metrics.awards_without_winner += not award.awardee_parties
                metrics.awards_without_value += award.value is None
                metrics.vat_categories[
                    (award.value.vat_category or "unspecified") if award.value else "no-value"
                ] += 1
                metrics.consortium_cases += any(p.is_group for p in award.awardee_parties)
                metrics.multi_party_independent += len(award.awardee_parties) > 1
                metrics.awards_with_referencing_pub += result.references_tender
                metrics.awards_without_referencing_pub += not result.references_tender
                metrics.awards_with_source_procedure_id += (
                    result.event.provenance.source_procedure_id is not None
                )
                metrics.awards_with_contract_reference += award.contract_reference is not None
            for warning in result.warnings:
                metrics.warnings[warning.code] += 1

            tender_documents = None
            if link and publication.referencing_pub_id:
                time.sleep(pause)
                tender_documents = _probe_tender(client, publication, metrics)

            print(
                f"[{index}/{len(refs)}] {publication.publication_number} "
                f"{ref.canton or '??'} {publication.project_type}/{publication.pub_type} "
                f"contrats={len(result.awards)} lot={'oui' if result.has_lot else 'non'} "
                f"docs={result.has_project_documents} tender_docs={tender_documents}"
            )
            detail.append(_detail(publication, result, ref, tender_documents))
            time.sleep(pause)

    if json_path:
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(
                {"metrics": metrics.as_dict(), "publications": detail},
                handle,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        print(f"détail écrit dans {json_path}", file=sys.stderr)
    return metrics


def _probe_tender(client: SimapClient, publication, metrics: Metrics) -> bool | None:
    """Mesure si l'appel d'offres d'origine SIGNALE des documents. N'en télécharge aucun."""
    try:
        tender = client.fetch_publication(publication.project_id, publication.referencing_pub_id)
    except SimapAuthRequiredError:
        metrics.auth_required_document_access_observed += 1
        return None
    except SimapError:
        return None
    metrics.linked_original_tenders += 1
    flag = bool(tender.get("hasProjectDocuments"))
    metrics.original_tenders_with_project_documents += flag
    return flag


def _detail(publication, result, ref, tender_documents) -> dict[str, object]:
    return {
        "publication_number": publication.publication_number,
        "publication_id": publication.publication_id,
        "project_id": publication.project_id,
        "project_number": publication.project_number,
        "pub_type": publication.pub_type,
        "project_type": publication.project_type,
        "project_sub_type": publication.project_sub_type,
        "process_type": publication.process_type,
        "canton": ref.canton,
        "published_at": str(result.event.published_at),
        "procedure_buyers": [b.legal_name for b in result.event.procedure_buyers],
        "referencing_pub_id": publication.referencing_pub_id,
        "referencing_pub_number": (
            publication.referencing_pub.publication_number if publication.referencing_pub else None
        ),
        "has_project_documents": result.has_project_documents,
        "tender_has_project_documents": tender_documents,
        "warnings": [str(w) for w in result.warnings],
        "awards": [
            {
                "lot": a.lot.identifier if a.lot else None,
                "winners": [o.legal_name for o in a.awardee_organizations()],
                "value": f"{a.value.canonical_amount()} {a.value.currency}" if a.value else None,
                "vat_category": a.value.vat_category if a.value else None,
                "cpv_main": a.cpv_main.code if a.cpv_main else None,
                "award_date": str(a.award_date) if a.award_date else None,
                "source_identity": a.source_identity(),
            }
            for a in result.awards
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test live du connecteur SIMAP")
    parser.add_argument("--limit", type=int, default=25, help="nombre de publications")
    parser.add_argument("--since", default="2026-07-01", help="publiées à partir de cette date")
    parser.add_argument("--pause", type=float, default=0.5, help="pause entre requêtes (s)")
    parser.add_argument(
        "--link", action="store_true", help="mesurer aussi les documents de l'appel d'offres"
    )
    parser.add_argument("--json", dest="json_path", default=None, help="fichier de détail")
    args = parser.parse_args()

    try:
        metrics = run(args.limit, args.since, args.pause, args.link, args.json_path)
    except SimapError as exc:
        print(f"simap.ch indisponible : {exc}", file=sys.stderr)
        return 2

    print("\n─── MÉTRIQUES ───")
    reported = metrics.as_dict()
    for key, value in reported.items():
        if key not in ("warnings", "failures", "vat_categories"):
            print(f"{key:42} {value}")
    print(f"{'vat_categories':42} {dict(metrics.vat_categories) or '—'}")
    print(f"{'warnings':42} {dict(metrics.warnings) or '—'}")
    if metrics.failures:
        print(f"{'failures':42} {metrics.failures}")
    return 1 if metrics.award_publications_parsed == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
