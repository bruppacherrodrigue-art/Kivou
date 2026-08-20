"""Pure deterministic ranking for commercial decision-maker candidates."""

from __future__ import annotations

import re
import unicodedata

from signals.contact_discovery.contracts import PeopleSearchCandidate, RankedCandidate
from signals.contact_discovery.profile import PERSON_TITLES


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_value = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_value).split())


_EXACT_TITLES = frozenset(_normalize(value) for value in PERSON_TITLES)
_TIER_PATTERNS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            "head of sales",
            "sales director",
            "vp sales",
            "commercial director",
            "chief revenue officer",
            "directeur commercial",
            "directeur des ventes",
        ),
    ),
    (
        2,
        (
            "business development director",
            "head of business development",
            "vp business development",
            "directeur du developpement commercial",
            "responsable developpement commercial",
        ),
    ),
    (
        3,
        (
            "sales manager",
            "business development manager",
            "responsable commercial",
            "responsable des ventes",
        ),
    ),
    (
        4,
        (
            "managing director",
            "ceo",
            "founder",
            "owner",
            "directeur general",
            "fondateur",
            "dirigeant",
        ),
    ),
)


def _tier(title: str) -> int | None:
    for tier, patterns in _TIER_PATTERNS:
        if any(pattern in title for pattern in patterns):
            return tier
    return None


def _seniority(title: str) -> int:
    terms = (
        ("chief", 1),
        ("ceo", 1),
        ("vp", 2),
        ("head", 3),
        ("director", 4),
        ("directeur", 4),
        ("manager", 5),
        ("responsable", 5),
        ("founder", 6),
        ("fondateur", 6),
        ("owner", 7),
        ("dirigeant", 7),
    )
    return next((priority for term, priority in terms if term in title), 20)


def rank_candidates(
    candidates: tuple[PeopleSearchCandidate, ...],
) -> tuple[RankedCandidate, ...]:
    ranked: list[RankedCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.provider_person_id in seen:
            continue
        seen.add(candidate.provider_person_id)
        normalized = _normalize(candidate.title)
        tier = _tier(normalized)
        if tier is None:
            continue
        ranked.append(
            RankedCandidate(
                candidate=candidate,
                normalized_title=normalized,
                role_tier=tier,
                exact_title_match=normalized in _EXACT_TITLES,
                seniority_priority=_seniority(normalized),
            )
        )
    return tuple(
        sorted(
            ranked,
            key=lambda item: (
                item.role_tier,
                not item.exact_title_match,
                item.seniority_priority,
                item.normalized_title,
                item.candidate.provider_person_id,
            ),
        )
    )
