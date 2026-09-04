"""Le moteur de matching — filtres durs d'abord, score expliqué ensuite.

    award-lot (ContractUnderstanding + NeedGraphResult) × TargetICP
      → hard filters (§21) : un échec n'est jamais compensé
      → quatre composants notés (§23) : besoin, économie, géographie, fraîcheur
      → normalisation sur les seules dimensions applicables
      → décision, bande, confiance, explication déterministe

Aucun appel LLM, aucune lecture d'horloge : `as_of` est toujours explicite
(§17). Aucun texte libre n'entre dans le calcul — `offer_summary` est inerte
(§8). L'unité de raisonnement est l'award-lot ; deux lots d'une même procédure
ne sont jamais fusionnés (§5).

Poids (§23, `signal-score-v0.1`), issus de l'étude de composants :

    need_offer_fit    45   dimension dominante (§24)
    economic_impact   20
    geography         20
    freshness_timing  15

`winner_fit` et `data_confidence` sont absents : le premier n'a aucune donnée
(0 adresse de gagnant sur 100 award-lots), le second est constant en mode
metadata et deviendrait un proxy du score général.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from signals.matching.icp import MATCH_POLICY_VERSION, TargetICP
from signals.matching.model import (
    SCORE_POLICY_VERSION,
    HardFilterResult,
    MatchDecision,
    ScoreBand,
    ScoredSignalMatch,
    SignalScoreComponent,
)
from signals.needs import NeedGraphResult
from signals.needs.features import scale_band
from signals.understanding.model import ContractUnderstanding

NEED_FIT_MAX = 45
ECONOMIC_MAX = 20
GEOGRAPHY_MAX = 20
FRESHNESS_MAX = 15

PRIMARY_FIT_POINTS = 45
SECONDARY_FIT_POINTS = 25
SECOND_NEED_BONUS = 5
"""Un second besoin correspondant vaut un bonus **borné** : le composant reste
plafonné à `NEED_FIT_MAX`, plusieurs besoins ne gonflent pas le score (§25)."""

SHOW_THRESHOLD = 60
BORDERLINE_THRESHOLD = 40
STRONG_BAND = 75
PROMISING_BAND = 55
"""Seuils calibrés sur DEV puis gelés avant le held-out (§27)."""


@dataclass(frozen=True)
class _Filter:
    result: HardFilterResult


class MatchingEngine:
    """Confronte un award-lot compris et ses besoins à un ICP déclaré."""

    match_policy_version = MATCH_POLICY_VERSION
    score_policy_version = SCORE_POLICY_VERSION

    def match(
        self,
        cu: ContractUnderstanding,
        needs: NeedGraphResult,
        icp: TargetICP,
        *,
        as_of: dt.date,
    ) -> ScoredSignalMatch:
        filters: list[HardFilterResult] = []

        produced = {need.category for need in needs.needs}
        primary_hits = tuple(c for c in icp.primary_need_categories if c in produced)
        secondary_hits = tuple(c for c in icp.secondary_need_categories if c in produced)
        matched = primary_hits + secondary_hits

        filters.append(
            HardFilterResult(
                name="source_mode",
                passed=needs.source_mode in icp.source_modes_allowed,
                detail=f"mode de production {needs.source_mode}",
            )
        )
        filters.append(
            HardFilterResult(
                name="need_overlap",
                passed=bool(matched),
                detail=(
                    f"besoins correspondants : {', '.join(matched)}"
                    if matched
                    else "aucun besoin de l'ICP n'est produit pour cet award-lot"
                ),
            )
        )
        trade_filter, trade_fit = self._trade_domain_filter(cu, icp)
        filters.append(trade_filter)
        filters.append(self._contract_type_filter(cu, icp))
        filters.append(self._sector_filter(cu, icp))
        filters.append(self._freshness_filter(cu, icp, as_of=as_of))
        geography_filter, geography_status = self._geography_filter(cu, icp)
        filters.append(geography_filter)
        value_filter, value_status = self._value_filter(cu, icp)
        filters.append(value_filter)

        blocked = [f for f in filters if not f.passed]
        inevaluable = [f for f in blocked if not f.evaluable]

        if blocked:
            decision: MatchDecision = "insufficient_data" if inevaluable else "exclude"
            return ScoredSignalMatch(
                award_ref=cu.award_ref,
                icp_id=icp.icp_id,
                as_of=as_of,
                decision=decision,
                band="excluded",
                confidence="medium",
                raw_points=0,
                maximum_applicable_points=0,
                normalized_score=0,
                score_components=(),
                hard_filter_results=tuple(filters),
                matched_needs=matched,
                positive_reasons=(),
                limitations=tuple(f.detail for f in blocked),
                evidence_refs=(),
                match_policy_version=MATCH_POLICY_VERSION,
                score_policy_version=SCORE_POLICY_VERSION,
            )

        components = [
            self._need_component(primary_hits, secondary_hits),
            self._economic_component(cu, value_status),
        ]
        if icp.geography_policy != "ignored":
            components.append(self._geography_component(geography_status))
        components.append(self._freshness_component(cu, needs, icp, as_of=as_of))

        raw = sum(component.points for component in components)
        ceiling = sum(component.maximum_points for component in components)
        normalized = round(100 * raw / ceiling) if ceiling else 0

        # §20 et rubrique §3 : le feed principal exige les trois appuis d'un
        # `strong_match` — un besoin PRIMAIRE, une géographie compatible quand
        # elle est applicable, et un appui économique réel. Un fit partiel reste
        # `borderline` : pertinent, mais pas assez pour le feed principal.
        geography_ok = geography_status in ("match", "ignored")
        economic_ok = value_status in ("within", "no_threshold_configured")
        # WEDGE-HARDENING R1 §18 — le métier est une PORTE, pas des points. Un
        # marché dont le métier n'est que « compatible » ou inconnu reste
        # pertinent — il descend en `borderline`, il ne disparaît pas.
        trade_ok = trade_fit in ("exact", "not_configured")
        decision = (
            "show"
            if normalized >= SHOW_THRESHOLD
            and primary_hits
            and geography_ok
            and economic_ok
            and trade_ok
            else "borderline"
            if normalized >= BORDERLINE_THRESHOLD
            else "exclude"
        )
        # §3 — la bande se lit DANS la décision, jamais à côté d'elle. Un score
        # élevé dont la décision est retombée à `borderline` (géographie ou
        # appui économique manquant) ne peut pas s'afficher `strong`.
        band: ScoreBand = (
            ("strong" if normalized >= STRONG_BAND else "promising")
            if decision == "show"
            else ("promising" if normalized >= PROMISING_BAND else "weak")
            if decision == "borderline"
            else "excluded"
        )

        reasons, limitations = self._explain(
            cu,
            needs,
            icp,
            primary_hits,
            secondary_hits,
            components,
            geography_status,
            value_status,
            trade_fit,
        )
        evidence = self._evidence(cu, needs, matched)

        return ScoredSignalMatch(
            award_ref=cu.award_ref,
            icp_id=icp.icp_id,
            as_of=as_of,
            decision=decision,
            band=band,
            confidence="medium",
            raw_points=raw,
            maximum_applicable_points=ceiling,
            normalized_score=normalized,
            score_components=tuple(components),
            hard_filter_results=tuple(filters),
            matched_needs=matched,
            positive_reasons=tuple(reasons) if decision != "exclude" else (),
            limitations=tuple(limitations),
            evidence_refs=tuple(evidence) if decision != "exclude" else (),
            match_policy_version=MATCH_POLICY_VERSION,
            score_policy_version=SCORE_POLICY_VERSION,
        )

    # ─── Filtres durs (§21) ────────────────────────────────────────────────

    @staticmethod
    def _trade_domain_filter(
        cu: ContractUnderstanding, icp: TargetICP
    ) -> tuple[HardFilterResult, str]:
        """Le métier du marché contre celui que l'ICP déclare vendre (§17).

        Quatre issues, et une cinquième qui est l'absence de règle :

        · `not_configured` — l'ICP ne déclare aucun métier : rien ne change.
        · `exact` — métier primaire : le marché peut atteindre le feed.
        · `compatible` — métier secondaire : pertinent, mais `borderline`.
        · `unknown` — le CPV ne dit pas le métier : `borderline`, jamais un
          `show`. Un `45000000` ne prouve pas une compatibilité (§13).
        · `incompatible` — métier explicitement hors cible : filtre dur.

        Le cas `incompatible` est ÉVALUABLE : ce n'est pas une donnée qui manque,
        c'est une donnée qui dit non. Le verdict est `exclude`, pas
        `insufficient_data`.
        """
        if not icp.primary_trade_domains:
            return (
                HardFilterResult(
                    name="trade_domain",
                    passed=True,
                    detail="l'ICP ne cible aucun corps de métier",
                ),
                "not_configured",
            )
        domain = cu.trade_domain.value if cu.trade_domain else "unknown_or_general"
        if domain in icp.primary_trade_domains:
            fit = "exact"
        elif domain in icp.secondary_trade_domains:
            fit = "compatible"
        elif domain == "unknown_or_general":
            fit = "unknown"
        else:
            fit = "incompatible"
        details = {
            "exact": f"corps de métier ciblé : {domain}",
            "compatible": f"corps de métier accepté en second : {domain}",
            "unknown": "le CPV publié ne dit pas le corps de métier",
            "incompatible": f"corps de métier hors cible : {domain}",
        }
        return (
            HardFilterResult(
                name="trade_domain",
                passed=fit != "incompatible",
                detail=details[fit],
            ),
            fit,
        )

    @staticmethod
    def _contract_type_filter(cu: ContractUnderstanding, icp: TargetICP) -> HardFilterResult:
        contract_type = cu.contract_type.value
        excluded = contract_type in icp.excluded_contract_types
        return HardFilterResult(
            name="contract_type",
            passed=not excluded,
            detail=(
                f"type de contrat {contract_type} explicitement exclu"
                if excluded
                else f"type de contrat {contract_type}"
            ),
        )

    @staticmethod
    def _sector_filter(cu: ContractUnderstanding, icp: TargetICP) -> HardFilterResult:
        sector = cu.sector.value
        cpv_claim = cu.facts.get("cpv")
        cpv = cpv_claim.value if cpv_claim is not None else None
        if icp.included_cpv_prefixes:
            if not cpv:
                return HardFilterResult(
                    name="cpv_sector",
                    passed=False,
                    evaluable=False,
                    detail="CPV absent : secteur ciblé inévaluable",
                )
            cpv_matches = any(cpv.startswith(prefix) for prefix in icp.included_cpv_prefixes)
            if not cpv_matches:
                return HardFilterResult(
                    name="cpv_sector",
                    passed=False,
                    detail=f"CPV {cpv} hors du secteur ciblé",
                )
        # Un secteur `unknown` ne bloque pas, et n'est jamais un point positif (§13).
        excluded = sector != "unknown" and sector in icp.excluded_sectors
        return HardFilterResult(
            name="sector",
            passed=not excluded,
            detail=(f"secteur {sector} explicitement exclu" if excluded else f"secteur {sector}"),
        )

    @staticmethod
    def _freshness_filter(
        cu: ContractUnderstanding, icp: TargetICP, *, as_of: dt.date
    ) -> HardFilterResult:
        published = cu.timing.published_at
        if published is None:
            return HardFilterResult(
                name="signal_age",
                passed=False,
                evaluable=False,
                detail="date de publication absente : la fraîcheur est inévaluable",
            )
        published_date = published.date() if hasattr(published, "date") else published
        age = (as_of - published_date).days
        return HardFilterResult(
            name="signal_age",
            passed=age <= icp.maximum_signal_age_days,
            detail=f"signal publié il y a {age} jours (plafond {icp.maximum_signal_age_days})",
        )

    @staticmethod
    def _geography_filter(
        cu: ContractUnderstanding, icp: TargetICP
    ) -> tuple[HardFilterResult, str]:
        """Rend le filtre et l'état géographique (`match`, `mismatch`, `unknown`)."""
        if icp.geography_policy == "ignored" or icp.geography_basis == "ignore":
            return (
                HardFilterResult(
                    name="geography", passed=True, detail="géographie non contraignante"
                ),
                "ignored",
            )

        place = cu.geography.place_of_performance
        candidates: list[str] = []
        if (
            icp.geography_basis in ("place_of_performance", "either")
            and place is not None
            and place.country
        ):
            candidates.append(place.country)
        # `winner_location` est modélisable mais sans données : aucune adresse de
        # gagnant n'existe dans le domaine actuel (§14). Aucun faux positif.

        if not candidates:
            return (
                HardFilterResult(
                    name="geography_missing",
                    passed=icp.geography_policy != "required",
                    evaluable=icp.geography_policy != "required",
                    detail="localisation absente pour la base géographique demandée",
                ),
                "unknown",
            )

        wanted_subdivisions = {
            (territory.country, territory.subdivision_code, territory.subdivision_scheme)
            for territory in icp.territories
            if territory.subdivision_code is not None
        }
        if wanted_subdivisions:
            subdivision = place.subdivision_code if place is not None else None
            if subdivision is None:
                return (
                    HardFilterResult(
                        name="geography_subdivision_missing",
                        passed=False,
                        evaluable=False,
                        detail="subdivision du lieu d'exécution absente",
                    ),
                    "unknown",
                )
            matched = (
                place.country,
                subdivision,
                place.subdivision_scheme,
            ) in wanted_subdivisions
        else:
            wanted = {territory.country for territory in icp.territories}
            matched = any(country in wanted for country in candidates)
        return (
            HardFilterResult(
                name="geography",
                passed=matched or icp.geography_policy == "preferred",
                detail=(
                    f"lieu d'exécution {', '.join(candidates)} dans la zone ciblée"
                    if matched
                    else f"lieu d'exécution {', '.join(candidates)} hors zone"
                ),
            ),
            "match" if matched else "mismatch",
        )

    @staticmethod
    def _value_filter(cu: ContractUnderstanding, icp: TargetICP) -> tuple[HardFilterResult, str]:
        """Rend le filtre et l'état de valeur pour le score."""
        amount_claim = cu.facts.get("amount")
        if amount_claim is None:
            return (
                HardFilterResult(
                    name="value_missing",
                    passed=icp.unknown_value_policy != "exclude",
                    evaluable=icp.unknown_value_policy != "exclude",
                    detail="montant absent",
                ),
                "missing",
            )
        try:
            raw_value, currency = amount_claim.value.rsplit(" ", 1)
            value = float(raw_value)
        except ValueError:
            return (
                HardFilterResult(name="value_unreadable", passed=True, detail="montant illisible"),
                "missing",
            )

        band = scale_band(amount_claim.value)
        if band == "not_material":
            # §16 — déjà neutralisé par SPEC-007 : aucun point économique.
            return (
                HardFilterResult(
                    name="value_threshold",
                    passed=True,
                    detail=f"montant non matériel ({amount_claim.value})",
                ),
                "not_material",
            )

        if not icp.value_thresholds:
            # L'ICP ne pose aucune contrainte de valeur : un montant connu et
            # matériel est un appui économique légitime.
            return (
                HardFilterResult(
                    name="value_threshold",
                    passed=True,
                    detail=f"aucun seuil configuré ; montant {value:.0f} {currency} connu",
                ),
                "no_threshold_configured",
            )
        threshold = icp.threshold_for(currency)
        if threshold is None:
            # §15 — aucune conversion : une devise sans seuil ne se compare pas.
            return (
                HardFilterResult(
                    name="value_currency",
                    passed=icp.unknown_value_policy != "exclude",
                    evaluable=icp.unknown_value_policy != "exclude",
                    detail=f"devise {currency} sans seuil correspondant",
                ),
                "currency_unsupported",
            )
        if value < threshold.minimum_amount:
            return (
                HardFilterResult(
                    name="value_threshold",
                    passed=False,
                    detail=(
                        f"montant {value:.0f} {currency} sous le minimum "
                        f"{threshold.minimum_amount:.0f}"
                    ),
                ),
                "below",
            )
        if threshold.maximum_amount is not None and value > threshold.maximum_amount:
            return (
                HardFilterResult(
                    name="value_threshold",
                    passed=False,
                    detail=(
                        f"montant {value:.0f} {currency} au-dessus du maximum "
                        f"{threshold.maximum_amount:.0f}"
                    ),
                ),
                "above",
            )
        return (
            HardFilterResult(
                name="value_threshold",
                passed=True,
                detail=f"montant {value:.0f} {currency} dans la fourchette ciblée",
            ),
            "within",
        )

    # ─── Composants (§22-§25) ──────────────────────────────────────────────

    @staticmethod
    def _need_component(
        primary_hits: tuple[str, ...], secondary_hits: tuple[str, ...]
    ) -> SignalScoreComponent:
        """Le meilleur match fonde le score ; un second n'ajoute qu'un bonus borné."""
        if primary_hits:
            base = PRIMARY_FIT_POINTS
            detail = f"besoin principal correspondant : {', '.join(primary_hits)}"
        else:
            base = SECONDARY_FIT_POINTS
            detail = f"besoin secondaire correspondant : {', '.join(secondary_hits)}"
        extra = len(primary_hits) + len(secondary_hits) - 1
        points = min(NEED_FIT_MAX, base + (SECOND_NEED_BONUS if extra > 0 else 0))
        return SignalScoreComponent(
            name="need_offer_fit",
            points=points,
            maximum_points=NEED_FIT_MAX,
            detail=detail,
        )

    @staticmethod
    def _economic_component(cu: ContractUnderstanding, value_status: str) -> SignalScoreComponent:
        amount_claim = cu.facts.get("amount")
        band = scale_band(amount_claim.value if amount_claim else None)
        points = {"very_large": 20, "large": 18, "modest": 12}.get(band, 0)
        if value_status in ("missing", "currency_unsupported", "not_material"):
            points = 0
        detail = (
            f"échelle économique {band}"
            if points
            else f"aucun point économique (échelle {band}, état {value_status})"
        )
        return SignalScoreComponent(
            name="economic_impact", points=points, maximum_points=ECONOMIC_MAX, detail=detail
        )

    @staticmethod
    def _geography_component(status: str) -> SignalScoreComponent:
        points = {"match": GEOGRAPHY_MAX}.get(status, 0)
        detail = {
            "match": "lieu d'exécution dans la zone ciblée",
            "mismatch": "lieu d'exécution hors de la zone ciblée",
            "unknown": "localisation absente : aucun point géographique",
        }.get(status, "géographie non évaluée")
        return SignalScoreComponent(
            name="geography", points=points, maximum_points=GEOGRAPHY_MAX, detail=detail
        )

    @staticmethod
    def _freshness_component(
        cu: ContractUnderstanding,
        needs: NeedGraphResult,
        icp: TargetICP,
        *,
        as_of: dt.date,
    ) -> SignalScoreComponent:
        """Fraîcheur et timing partagent un composant unique, plafonné (§24)."""
        published = cu.timing.published_at
        published_date = published.date() if hasattr(published, "date") else published
        age = (as_of - published_date).days
        freshness = 10 if age <= 30 else 6 if age <= 60 else 3 if age <= 90 else 0

        timings = {need.timing for need in needs.needs}
        preferred = set(icp.preferred_timings)
        # Un timing `unknown` ne rapporte jamais de point positif (§18).
        timing_points = 5 if preferred and (timings & preferred) else 0

        points = min(FRESHNESS_MAX, freshness + timing_points)
        return SignalScoreComponent(
            name="freshness_timing",
            points=points,
            maximum_points=FRESHNESS_MAX,
            detail=(
                f"publié il y a {age} jours"
                + (
                    f" ; timing {', '.join(sorted(timings & preferred))} recherché"
                    if timing_points
                    else " ; aucun timing préféré établi"
                )
            ),
        )

    # ─── Explication déterministe (§28) ────────────────────────────────────

    @staticmethod
    def _explain(
        cu,
        needs,
        icp,
        primary_hits,
        secondary_hits,
        components,
        geography_status,
        value_status,
        trade_fit,
    ) -> tuple[list[str], list[str]]:
        reasons: list[str] = []
        limitations: list[str] = []

        if primary_hits:
            reasons.append(f"besoin principal de l'ICP couvert : {', '.join(primary_hits)}")
        if secondary_hits:
            reasons.append(f"besoin secondaire également couvert : {', '.join(secondary_hits)}")
        if not primary_hits:
            limitations.append(
                "aucun besoin principal ne correspond : le fit repose sur une offre secondaire"
            )

        economic = next(c for c in components if c.name == "economic_impact")
        if economic.points:
            amount = cu.facts["amount"].value
            reasons.append(f"marché de {amount}")
        elif value_status == "missing":
            limitations.append("montant non publié : aucun point économique")
        elif value_status == "currency_unsupported":
            limitations.append(
                "devise sans seuil configuré : aucune comparaison monétaire n'est faite"
            )
        elif value_status == "not_material":
            limitations.append("montant non matériel : aucun point économique")

        if trade_fit == "exact":
            reasons.append(f"corps de métier ciblé : {cu.trade_domain.value}")
        elif trade_fit == "compatible":
            limitations.append(
                f"corps de métier « {cu.trade_domain.value} » accepté en second : les "
                "intrants de ce marché peuvent passer par un autre canal d'achat"
            )
        elif trade_fit == "unknown":
            limitations.append(
                "le CPV publié ne dit pas le corps de métier : la compatibilité avec "
                "l'offre du client n'est pas établie"
            )

        if geography_status == "match":
            reasons.append("lieu d'exécution dans la zone ciblée")
        elif geography_status == "unknown" and icp.geography_policy == "preferred":
            limitations.append("localisation absente : la préférence géographique n'a pas joué")
        elif geography_status == "mismatch":
            limitations.append("lieu d'exécution hors de la zone ciblée")

        freshness = next(c for c in components if c.name == "freshness_timing")
        if freshness.points:
            reasons.append(freshness.detail)
        if all(need.timing == "unknown" for need in needs.needs):
            limitations.append("aucune date de début publiée : le timing reste indéterminé")

        # Toujours dit, jamais implicite : c'est la limite du mode courant (§4).
        limitations.append(
            "besoins inférés depuis les métadonnées de l'avis, sans exigence documentaire validée"
        )
        return reasons, limitations

    @staticmethod
    def _evidence(cu, needs, matched) -> list:
        """Les preuves des FAITS ayant rapporté des points — jamais du futur (§29)."""
        seen: dict[int, object] = {}
        for need in needs.needs:
            if need.category in matched:
                for evidence in need.evidence_refs:
                    seen[id(evidence)] = evidence
        for key in ("amount", "cpv"):
            claim = cu.facts.get(key)
            if claim:
                for evidence in claim.evidence:
                    seen[id(evidence)] = evidence
        for evidence in cu.contract_type.evidence:
            seen[id(evidence)] = evidence
        return list(seen.values())
