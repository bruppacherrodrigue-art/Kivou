"""Smoke test live des registres — volontaire, jamais lancé par la suite de tests.

    uv run python -m signals.resolution.live_smoke --benchmark
    uv run python -m signals.resolution.live_smoke --zefix

Interroge VIES pour de vrais numéros de TVA **déjà publiés** dans les avis, et
constate l'état d'accès à Zefix. Aucun numéro n'est deviné, aucun compte n'est
créé, aucun registre n'est aspiré : le cache garantit une requête par entreprise.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

from signals.domain import OrganizationRef
from signals.resolution.registries import RegistryAuthRequiredError, ViesClient, ZefixClient
from signals.resolution.resolver import CompanyResolver

BENCHMARK = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "winner100"


def run_benchmark(path: Path) -> int:
    """Rejoue le Winner-100 contre les registres réels."""
    mentions = json.loads((path / "mentions.json").read_text(encoding="utf-8"))
    with ViesClient() as vies:
        resolver = CompanyResolver(vies=vies)
        resolutions = [
            resolver.resolve(
                OrganizationRef.model_validate(row["organization"]), source_system=row["source"]
            )
            for row in mentions
        ]
        statuses = collections.Counter(resolution.status for resolution in resolutions)

        print("─── WINNER-100 (registres réels) ───")
        for status in (
            "verified",
            "probable",
            "review_required",
            "unresolved",
            "conflict",
            "registry_unavailable",
        ):
            print(f"{status:24} {statuses.get(status, 0)}")
        print()
        print(f"{'entreprises distinctes':24} {len(resolver.companies)}")
        clusters = resolver.clusters()
        print(f"{'clusters same-source':24} {sum(1 for _, n, _ in clusters if n > 1)}")
        print(f"{'clusters cross-source':24} {sum(1 for _, _, s in clusters if len(s) > 1)}")
        print()
        print(f"{'VIES tentées':24} {resolver.stats.vies_attempted}")
        print(f"{'VIES valides':24} {resolver.stats.vies_valid}")
        print(f"{'VIES invalides':24} {resolver.stats.vies_invalid}")
        print(f"{'VIES indisponibles':24} {resolver.stats.vies_unavailable}")
        print(f"{'requêtes envoyées':24} {vies.requests_sent}")
        print(f"{'économisées par le cache':24} {vies.cache_hits}")
        print(f"{'liens automatiques':24} {resolver.stats.automatic_links}")

        print("\n─── vérifiées par registre ───")
        for resolution in resolutions:
            if resolution.status == "verified":
                print(f"  {resolution.source_organization.legal_name[:44]:<44}")
                for basis in resolution.basis:
                    print(f"      {basis}")

        print("\n─── à vérifier par un humain ───")
        for resolution in resolutions:
            if resolution.needs_human:
                print(f"  [{resolution.status}] {resolution.source_organization.legal_name}")
                for basis in resolution.basis:
                    print(f"      {basis}")
    return 0 if resolutions else 1


def probe_zefix() -> int:
    """Constate l'état d'accès au registre du commerce suisse."""
    client = ZefixClient()
    print("Zefix PublicREST API — tous les endpoints exigent `Zefix-Credentials`.")
    try:
        client.search_by_name("Egli Gartenbau AG")
    except RegistryAuthRequiredError as exc:
        print(f"AUTH REQUIRED — {exc}")
        print("Aucune requête n'a été émise, aucun compte n'a été créé.")
        return 0
    print("Identifiants présents : le registre est interrogeable.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test live des registres")
    parser.add_argument("--benchmark", action="store_true", help="rejouer le Winner-100")
    parser.add_argument("--zefix", action="store_true", help="constater l'accès Zefix")
    parser.add_argument("--path", default=str(BENCHMARK), help="dossier du benchmark")
    args = parser.parse_args()

    if args.zefix:
        return probe_zefix()
    if args.benchmark:
        return run_benchmark(Path(args.path))
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
