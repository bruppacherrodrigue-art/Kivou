"""Libellés CPV 2008 (vocabulaire commun des marchés publics).

Le jeu (`data/cpv_2008.json`) est la nomenclature officielle CPV 2008 de
l'Office des publications de l'UE, republiée par OpenDataSoft — voir
`SOURCE.md`. Il est **committé**, jamais régénéré à l'exécution : l'import
(`import_cpv.py`) est un script ponctuel, hors ligne.

Un CPV publié porte parfois un chiffre de contrôle (`45262311-4`) ; le code
persisté par `contract_award.cpv_main` est déjà la forme à 8 chiffres.
`cpv_label` normalise dans les deux cas : chiffres seuls, tronqués aux 8
premiers.

La nomenclature CPV est hiérarchique par zéros de fin (`45262311` est un
enfant de `45262300`, lui-même de `45262000`, etc. jusqu'à `45000000`). Un code
absent du jeu (rare : certains codes très spécifiques ne portent pas de
libellé propre dans l'export) retombe sur son parent le plus proche.
"""

from __future__ import annotations

import json
from pathlib import Path

_DATA_PATH = Path(__file__).parent / "data" / "cpv_2008.json"
_SUPPORTED_LANGS = frozenset({"fr", "en"})

# Niveaux officiels de la hiérarchie CPV, du plus précis au plus large :
# détail (8 chiffres), sous-catégorie (6), catégorie (5), classe (4), groupe
# (3), division (2). Les positions 7-8 forment ensemble la précision la plus
# fine et ne constituent pas un niveau à elles seules : on saute directement
# de 8 à 6 chiffres significatifs.
_FALLBACK_LEVELS: tuple[int, ...] = (8, 6, 5, 4, 3, 2)

_cache: dict[str, dict[str, str]] | None = None


def _load() -> dict[str, dict[str, str]]:
    """Charge le jeu CPV depuis le disque une seule fois, au premier accès."""
    global _cache
    if _cache is None:
        with _DATA_PATH.open("r", encoding="utf-8") as handle:
            _cache = json.load(handle)
    return _cache


def __getattr__(name: str) -> dict[str, dict[str, str]]:
    # PEP 562 : `CPV_LABELS` n'est chargé qu'au premier accès à l'attribut du
    # module, pas à l'import (qui doit rester bon marché).
    if name == "CPV_LABELS":
        return _load()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _normalize_code(code: str) -> str | None:
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) < 8:
        return None
    return digits[:8]


def cpv_label(code: str | None, *, lang: str) -> str | None:
    """Le libellé du code CPV, avec repli par préfixe décroissant.

    `code` est normalisé (chiffres seuls, tronqués aux 8 premiers). Sans
    correspondance exacte, on complète de zéros par la droite en raccourcissant
    le préfixe significatif d'un cran à la fois (`45262311` → `45262300` →
    `45262000` → `45260000` → `45200000` → `45000000`) jusqu'à trouver une
    entrée ou épuiser les niveaux CPV. `lang` hors `{"fr", "en"}` retombe sur
    `fr`.
    """
    if not code:
        return None
    normalized = _normalize_code(code)
    if normalized is None:
        return None
    effective_lang = lang if lang in _SUPPORTED_LANGS else "fr"
    labels = _load()
    for level in _FALLBACK_LEVELS:
        candidate = normalized[:level].ljust(8, "0")
        entry = labels.get(candidate)
        if entry is not None:
            return entry.get(effective_lang)
    return None


def cpv_divisions(*, lang: str) -> tuple[tuple[str, str], ...]:
    """Retourne les divisions CPV officielles sous forme ``(préfixe, libellé)``."""
    effective_lang = lang if lang in _SUPPORTED_LANGS else "fr"
    return tuple(
        (code[:2], entry[effective_lang])
        for code, entry in sorted(_load().items())
        if len(code) == 8 and code.endswith("000000") and entry.get(effective_lang)
    )


__all__ = ["CPV_LABELS", "cpv_divisions", "cpv_label"]
