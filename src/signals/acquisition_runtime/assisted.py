"""Terminal assisted-mode action: prepare review rows and never transport."""

from __future__ import annotations

from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from signals.acquisition_runtime.contracts import RuntimeActionResult, RuntimeStageStatus
from signals.acquisition_runtime.registry import AcquisitionActionContext
from signals.acquisition_runtime.selection import resolved_holder_for_opportunity
from signals.decision_engine.policy import semantic_fingerprint
from signals.domain.award_dates import attribution_date
from signals.domain.subdivisions import subdivision_label
from signals.prospection_actions.preparation_contracts import (
    AssistedSignal,
    PreparationResult,
)
from signals.supplier_discovery.families import (
    department_from_subdivision,
    families_for_signal,
    load_supplier_family_catalog,
)
from signals.supplier_discovery.seed import resolve_acquisition_seed


class PreparationPort(Protocol):
    def prepare(self, signal, *, cycle_ref: str) -> PreparationResult: ...


def resolve_assisted_signal(
    engine,
    opportunity_key: str,
    *,
    required_family_key: str | None = None,
    representative_award_key: str | None = None,
) -> AssistedSignal:
    seed = resolve_acquisition_seed(
        engine,
        opportunity_key,
        representative_award_key=representative_award_key,
    )
    award = seed.award
    amount = award.value
    place = award.place_of_performance
    lot_title = str(award.lot.title or "").strip() if award.lot is not None else ""
    title = str(lot_title or award.title or award.description or "").strip()
    official_holder = resolved_holder_for_opportunity(
        engine,
        opportunity_key,
        source_award_key=representative_award_key,
    )
    holder = None if official_holder is None else official_holder.name
    holder_siren = None
    if official_holder is not None:
        identifier = str(official_holder.identifier_value or "")
        if official_holder.identifier_scheme and official_holder.identifier_scheme.casefold() == "siret":
            identifier = identifier[:9]
        if len(identifier) == 9 and identifier.isdigit():
            holder_siren = identifier
    if holder is None:
        holder = next(
            (
                str(organization.legal_name).strip()
                for organization in award.awardee_organizations()
                if str(organization.legal_name).strip()
            ),
            None,
        )
    subdivision = place.subdivision_code if place else None
    department = department_from_subdivision(subdivision)
    decision_date = attribution_date(award)
    if not title or holder is None or amount is None or department is None or decision_date is None:
        raise ValueError("assisted signal is missing a required eligibility fact")
    cpv_codes = tuple(
        value
        for value in (
            award.cpv_main.code if award.cpv_main else None,
            *(str(code) for code in award.cpv_additional),
        )
        if value
    )
    if required_family_key is None:
        if seed.understanding.trade_domain is None:
            raise ValueError("assisted signal has no materialized trade domain")
        vertical = seed.understanding.trade_domain.value
    else:
        vertical = next(
            (
                catalog_vertical
                for catalog_vertical, catalog_families in load_supplier_family_catalog().items()
                if required_family_key in {family.key for family in catalog_families}
            ),
            None,
        )
        if vertical is None:
            raise ValueError("assisted signal requires an unknown supplier family")
    families = families_for_signal(
        vertical,
        cpv_codes=cpv_codes,
        object_text=" ".join(
            filter(None, (lot_title, award.title, award.description))
        ),
    )
    if required_family_key is not None:
        families = tuple(family for family in families if family.key == required_family_key)
        if not families:
            raise ValueError("assisted signal does not match the required family")
    location = (
        (str(place.locality) if place and place.locality else None)
        or subdivision_label(subdivision)
        or department
    )
    city = str(place.locality).strip() if place and place.locality else None
    source_url = str(seed.event.provenance.source_url or "").strip()
    if not source_url:
        raise ValueError("assisted signal has no public source URL")
    return AssistedSignal(
        opportunity_key=opportunity_key,
        acquisition_opportunity_id=semantic_fingerprint(
            {"kind": "assisted-signal-v1", "opportunity_key": opportunity_key}
        ),
        procedure_key=seed.event.ref().key(),
        holder=holder,
        holder_siren=holder_siren,
        holder_family_required=True,
        target_holder_family=required_family_key is not None,
        subject=title[:998],
        amount_minor_units=int(
            (Decimal(amount.amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        ),
        currency=str(amount.currency).casefold(),
        location=location,
        city=city,
        department=department,
        decision_date=decision_date,
        source_url=source_url,
        vertical=vertical,
        families=tuple((family.key, family.label_fr) for family in families),
    )


class AssistedPreparationAction:
    def __init__(
        self,
        *,
        preparation: PreparationPort,
        signal_resolver: Callable[[str], object],
        enrichment_handler: Callable[[AcquisitionActionContext], RuntimeActionResult]
        | None = None,
    ) -> None:
        self._preparation = preparation
        self._signal_resolver = signal_resolver
        self._enrichment_handler = enrichment_handler

    def __call__(self, context: AcquisitionActionContext) -> RuntimeActionResult:
        try:
            signal = self._signal_resolver(context.cycle.opportunity_key)
            result = self._preparation.prepare(signal, cycle_ref=context.cycle.cycle_ref)
            enrichment = None
            if result.enrichment_required and self._enrichment_handler is not None:
                enrichment = self._enrichment_handler(context)
                refreshed = self._preparation.prepare(
                    signal, cycle_ref=context.cycle.cycle_ref
                )
                result = PreparationResult(
                    prepared=result.prepared + refreshed.prepared,
                    status="pending_review",
                    target_ids=result.target_ids + refreshed.target_ids,
                    reason=refreshed.reason,
                    directory_candidates=max(
                        result.directory_candidates,
                        refreshed.directory_candidates,
                    ),
                    enrichment_required=refreshed.enrichment_required,
                )
        except ValueError:
            return RuntimeActionResult(
                status=RuntimeStageStatus.SUPPRESSED,
                reason_codes=("ASSISTED_SIGNAL_NOT_ELIGIBLE",),
            )
        reason = result.reason or (
            "ASSISTED_PENDING_REVIEW" if result.prepared else "ASSISTED_TARGET_NOT_FOUND"
        )
        batch_ref = semantic_fingerprint(
            {
                "kind": "assisted-prospect-batch-v1",
                "cycle_ref": context.cycle.cycle_ref,
                "target_ids": result.target_ids,
                "reason": reason,
            }
        )
        return RuntimeActionResult(
            status=RuntimeStageStatus.SUPPRESSED,
            result_refs=(batch_ref,),
            reason_codes=(reason,),
            reserved_cost=(enrichment.reserved_cost if enrichment is not None else 0),
            observed_cost=(enrichment.observed_cost if enrichment is not None else 0),
        )


def build_assisted_preparation_action(
    engine,
    *,
    preparation: PreparationPort,
    enrichment_handler: Callable[[AcquisitionActionContext], RuntimeActionResult]
    | None = None,
    required_family_key: str | None = None,
) -> AssistedPreparationAction:
    return AssistedPreparationAction(
        preparation=preparation,
        signal_resolver=lambda opportunity_key: resolve_assisted_signal(
            engine,
            opportunity_key,
            required_family_key=required_family_key,
        ),
        enrichment_handler=enrichment_handler,
    )


__all__ = [
    "AssistedPreparationAction",
    "build_assisted_preparation_action",
    "resolve_assisted_signal",
]
