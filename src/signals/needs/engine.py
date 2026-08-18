"""Le moteur Need Graph V0 — mécanisme ET pression, déterministe, borné.

    ContractUnderstanding (un award-lot)
      → faits classés par rôle (features.py)
      → règles applicables : ≥ 1 mécanisme ET ≥ 1 pression (rules.py)
      → gardes négatives : recouvrement livrable, profil, échelle non matérielle
      → liaison des preuves : l'Evidence des faits d'entrée, jamais du futur
      → déduplication par catégorie canonique
      → ranking déterministe → top 0-3

SPEC-007R1 §18 : l'unité de raisonnement est l'**award-lot**. Une notice peut
produire plusieurs `ContractAward` ; le moteur ne les fusionne jamais.

Aucun appel LLM (§24), aucune lecture des sorties expérimentales SPEC-006
(§27) : le mode est `metadata_fallback`, et il est écrit sur chaque besoin.

Ranking (§18), documenté : score = 10 × nombre de pressions distinctes + 5 si
l'échelle est `large`/`very_large` + 2 si le timing est connu ; à égalité,
l'ordre de priorité des catégories tranche. Ce score ne sert qu'à borner la
sortie à trois besoins — ce n'est pas le Signal Score de SPEC-008.
"""

from __future__ import annotations

from dataclasses import dataclass

from signals.needs.features import (
    MECHANISM_FACTS,
    PRESSURE_FACTS,
    NeedFeatures,
    extract_features,
)
from signals.needs.model import (
    ENGINE_VERSION,
    MAX_NEEDS,
    NeedGraphResult,
    ResourceNeed,
    SuppressedCandidate,
)
from signals.needs.rules import (
    DELIVERABLE_OVERLAP,
    PROFILE_OVERLAP,
    RULE_LIBRARY,
    NeedRule,
)
from signals.understanding.model import ContractUnderstanding

_CATEGORY_PRIORITY = (
    "workforce_capacity",
    "equipment_or_rental",
    "materials_or_components",
    "logistics_and_transport",
    "specialist_subcontracting",
    "safety_and_ppe",
    "waste_and_environment",
)


@dataclass(frozen=True)
class _Candidate:
    rule: NeedRule
    mechanisms: tuple[str, ...]
    pressures: tuple[str, ...]

    @property
    def supporting_facts(self) -> tuple[str, ...]:
        facts = [MECHANISM_FACTS[m] for m in self.mechanisms]
        facts += [PRESSURE_FACTS[p] for p in self.pressures]
        return tuple(dict.fromkeys(facts))


SUBJECT_MAX_CHARS = 120
"""Un sujet doit tenir dans une phrase lisible. Au-delà, il est coupé — jamais
résumé : couper est vérifiable, résumer serait réécrire l'avis."""


def _subject(features: NeedFeatures) -> str | None:
    """L'objet publié, complété du corps de métier quand le CPV le donne.

    `unknown_or_general` n'est jamais affiché : dire « métier inconnu » à côté
    d'un objet publié n'ajoute rien et alourdit la phrase.
    """
    # Les avis publient des objets sur plusieurs lignes — listes de postes,
    # métrés. Le sujet est une phrase : les blancs sont réduits, jamais le texte.
    published = " ".join((features.published_object or "").split())
    if not published:
        return None
    if len(published) > SUBJECT_MAX_CHARS:
        published = published[: SUBJECT_MAX_CHARS - 1].rstrip() + "…"
    if features.trade_domain != "unknown_or_general":
        return f"{published} ({features.trade_domain})"
    return published


class NeedGraphEngine:
    """Transforme un award-lot compris en 0 à 3 hypothèses commerciales."""

    version = ENGINE_VERSION

    def __init__(self, rules: tuple[NeedRule, ...] = RULE_LIBRARY) -> None:
        self.rules = rules

    def derive(self, cu: ContractUnderstanding) -> NeedGraphResult:
        features = extract_features(cu)
        forbidden = DELIVERABLE_OVERLAP.get(features.contract_type, frozenset())
        forbidden |= PROFILE_OVERLAP.get(features.construction_profile, frozenset())

        candidates: list[_Candidate] = []
        suppressed: list[SuppressedCandidate] = []

        for rule in self.rules:
            mechanisms = tuple(m for m in rule.mechanism_predicates if features.mechanism(m))
            if not mechanisms:
                continue  # la règle ne parle pas de ce contrat : rien à diagnostiquer
            if rule.category in forbidden:
                suppressed.append(
                    SuppressedCandidate(
                        category=rule.category,
                        rule_id=rule.rule_id,
                        reason="deliverable_overlap",
                    )
                )
                continue
            # §10 — un montant dérisoire ne porte aucun raisonnement, même si
            # d'autres pressions existent : le diagnostic le nomme.
            if features.scale_band == "not_material":
                suppressed.append(
                    SuppressedCandidate(
                        category=rule.category,
                        rule_id=rule.rule_id,
                        reason="scale_not_material",
                    )
                )
                continue
            pressures = tuple(p for p in rule.pressure_predicates if features.pressure(p))
            if not pressures:
                # Mécanisme sans pression : `plausible_but_weak` au sens de la
                # rubrique — un candidat `low`, jamais un besoin `medium` (§5).
                suppressed.append(
                    SuppressedCandidate(
                        category=rule.category,
                        rule_id=rule.rule_id,
                        reason="no_pressure_fact",
                    )
                )
                continue
            candidates.append(_Candidate(rule=rule, mechanisms=mechanisms, pressures=pressures))

        merged = self._deduplicate(candidates)
        ranked = sorted(
            merged,
            key=lambda item: (
                -self._score(item, features),
                _CATEGORY_PRIORITY.index(item[0].rule.category),
            ),
        )

        needs = tuple(self._need(primary, group, features) for primary, group in ranked[:MAX_NEEDS])
        for primary, _ in ranked[MAX_NEEDS:]:
            suppressed.append(
                SuppressedCandidate(
                    category=primary.rule.category,
                    rule_id=primary.rule.rule_id,
                    reason="ranked_below_top_three",
                )
            )

        return NeedGraphResult(
            award_ref=cu.award_ref,
            source_mode="metadata_fallback",
            needs=needs,
            suppressed_candidates=tuple(suppressed),
            warnings=(),
            engine_version=ENGINE_VERSION,
        )

    @staticmethod
    def _deduplicate(candidates: list[_Candidate]) -> list[tuple[_Candidate, list[_Candidate]]]:
        """§17 — une catégorie canonique = un besoin, tous les rule_ids conservés."""
        by_category: dict[str, list[_Candidate]] = {}
        for candidate in candidates:
            by_category.setdefault(candidate.rule.category, []).append(candidate)
        return [
            (max(group, key=lambda c: len(set(c.supporting_facts))), group)
            for group in by_category.values()
        ]

    @staticmethod
    def _score(item: tuple[_Candidate, list[_Candidate]], features: NeedFeatures) -> int:
        _, group = item
        pressures = {p for candidate in group for p in candidate.pressures}
        score = 10 * len(pressures)
        if features.scale_band in ("large", "very_large"):
            score += 5
        if features.timing != "unknown":
            score += 2
        return score

    @staticmethod
    def _need(primary: _Candidate, group: list[_Candidate], features: NeedFeatures) -> ResourceNeed:
        facts = tuple(dict.fromkeys(f for c in group for f in c.supporting_facts))
        evidence = tuple(
            {
                id(ev): ev
                for fact in facts
                if fact in features.claims
                for ev in features.claims[fact].evidence
            }.values()
        )
        # §20 — `external_plausible` exige plusieurs indices convergents ; sinon
        # la règle la plus prudente s'applique.
        externalisability = primary.rule.externalisability
        pressures = {p for candidate in group for p in candidate.pressures}
        if externalisability == "external_plausible" and len(pressures) < 2:
            externalisability = "mixed"
        # WEDGE-HARDENING R1 §19–§21 — l'hypothèse nomme son sujet et reste
        # révocable par lui. Deux faits canoniques seulement : l'objet publié
        # tel quel, et le corps de métier porté par le CPV. Aucune reformulation,
        # aucun mot-clé lu dans le texte.
        subject = _subject(features)
        reasoning = primary.rule.reasoning_template
        if subject:
            reasoning += (
                f" Elle porte sur l'objet publié « {subject} » : si cet objet ne "
                "relève pas de ces travaux, elle ne tient pas."
            )
        else:
            reasoning += (
                " L'avis ne publie aucun objet exploitable pour ce lot : l'hypothèse "
                "repose sur le seul code CPV et reste à ce titre plus fragile."
            )
        return ResourceNeed(
            category=primary.rule.category,
            subject=subject,
            statement=primary.rule.statement_template,
            reasoning=reasoning,
            timing=features.timing,
            externalisability=externalisability,
            confidence="medium",
            evidence_refs=evidence,
            supporting_facts=facts,
            mechanism_facts=tuple(dict.fromkeys(m for c in group for m in c.mechanisms)),
            pressure_facts=tuple(dict.fromkeys(p for c in group for p in c.pressures)),
            rule_ids=tuple(dict.fromkeys(c.rule.rule_id for c in group)),
            source_mode="metadata_fallback",
            engine_version=ENGINE_VERSION,
        )
