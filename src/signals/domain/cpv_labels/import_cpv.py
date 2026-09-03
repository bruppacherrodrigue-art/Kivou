"""Importe la nomenclature CPV 2008 depuis l'export CSV OpenDataSoft.

Usage : `python -m signals.domain.cpv_labels.import_cpv <csv> <out.json>`.

Le CSV source (voir `SOURCE.md`) porte les colonnes
`code;de;en;es;fr;pt;code_short`, séparateur `;`, BOM UTF-8. `code` est le CPV
complet avec chiffre de contrôle (`19724000-7`), `code_short` la forme à 8
chiffres — c'est cette dernière qui sert de clé, car c'est la forme persistée
par `contract_award.cpv_main`.

Ce script ne tourne jamais en test : le jeu généré (`data/cpv_2008.json`) est
committé, pas régénéré à la volée.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def build_labels(csv_path: Path) -> dict[str, dict[str, str]]:
    """Lit le CSV source et rend `{"<code 8 chiffres>": {"fr": ..., "en": ...}}`."""
    labels: dict[str, dict[str, str]] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            code_short = (row.get("code_short") or "").strip()
            fr = (row.get("fr") or "").strip()
            en = (row.get("en") or "").strip()
            if not code_short or not fr or not en:
                continue
            labels[code_short] = {"fr": fr, "en": en}
    return labels


def write_labels(labels: dict[str, dict[str, str]], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(labels, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python -m signals.domain.cpv_labels.import_cpv <csv> <out.json>", file=sys.stderr)
        return 2
    csv_path = Path(argv[1])
    out_path = Path(argv[2])
    labels = build_labels(csv_path)
    write_labels(labels, out_path)
    print(f"{len(labels)} codes CPV écrits dans {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
