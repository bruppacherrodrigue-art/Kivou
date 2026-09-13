"""Validated, read-only consultation scope shared by the three prospecting tabs."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from decimal import Decimal, InvalidOperation

from signals.accounts import service as accounts
from signals.accounts.icp_input import offer_for_need
from signals.api.errors import api_error
from signals.billing.access import FilterNotEntitled, check_filters
from signals.domain.french_departments import location_subdivision
from signals.domain.subdivisions import subdivision_label


def context_fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:24]


@dataclasses.dataclass(frozen=True)
class ConsultationScope:
    target_icp_id: str | None = None
    matching_revision: int = 0
    offer_category: str | None = None
    subdivision_code: str | None = None
    min_amount: Decimal | None = None
    amount_currency: str | None = None
    offer_categories: tuple[str, ...] = ()
    context_tag: str = ""

    def payload(self) -> dict:
        return {
            **dataclasses.asdict(self),
            "min_amount": str(self.min_amount) if self.min_amount is not None else None,
            "offer_categories": list(self.offer_categories),
        }

    def matches(self, signal) -> bool:
        if self.target_icp_id is not None and signal.target_icp_id != self.target_icp_id:
            return False
        if self.offer_category is not None and not any(
            offer_for_need(need) == self.offer_category for need in signal.icp_matched_needs
        ):
            return False
        if (
            self.subdivision_code is not None
            and location_subdivision(signal.award.place_of_performance or {})
            != self.subdivision_code
        ):
            return False
        if self.amount_currency is not None and signal.award.currency != self.amount_currency:
            return False
        return not (
            self.min_amount is not None
            and (signal.award.amount is None or signal.award.amount < self.min_amount)
        )


def resolve_scope(
    connection,
    *,
    account_id: str,
    entitlements,
    allowed_target_icp_ids,
    target_icp_id=None,
    offer_category=None,
    subdivision_code=None,
    min_amount=None,
    amount_currency=None,
    query_parameters=None,
) -> ConsultationScope:
    if query_parameters is not None and "account_id" in query_parameters:
        raise api_error(422, "invalid_input", "le compte vient de la session")
    profiles = accounts.list_target_icps(connection, account_id=account_id)
    profile = next((row for row in profiles if row.target_icp_id == target_icp_id), None)
    if target_icp_id is not None and profile is None:
        raise api_error(404, "target_icp_not_found", "profil de ciblage introuvable")
    if (
        profile is not None
        and profile.status == "active"
        and profile.target_icp_id not in allowed_target_icp_ids
    ):
        raise api_error(
            403,
            "filter_not_entitled",
            "ce profil dépasse les droits du plan",
            filter="target_icp_id",
        )
    considered = (
        [profile]
        if profile is not None
        else [row for row in profiles if row.target_icp_id in allowed_target_icp_ids]
    )
    offers = tuple(
        sorted(
            {
                offer
                for row in considered
                for offer in (
                    *row.customer_input.offers,
                    *row.customer_input.secondary_offers,
                )
            }
        )
    )
    if offer_category is not None and offer_category not in offers:
        raise api_error(422, "invalid_input", "offre absente du profil", field="offer_category")
    if subdivision_code is not None and profile is not None:
        customer = profile.customer_input
        if not subdivision_label(subdivision_code) or (
            subdivision_code not in customer.territory_subdivisions
            if customer.territory_subdivisions
            else subdivision_code.split("-", 1)[0] not in customer.territories
        ):
            raise api_error(
                422, "invalid_input", "zone absente du profil", field="subdivision_code"
            )
    if amount_currency is not None and amount_currency not in ("EUR", "CHF"):
        raise api_error(422, "invalid_input", "devise non prise en charge", field="amount_currency")
    if min_amount is not None:
        try:
            min_amount = Decimal(str(min_amount))
        except InvalidOperation as error:
            raise api_error(422, "invalid_input", "montant invalide", field="min_amount") from error
        if not min_amount.is_finite() or min_amount < 0:
            raise api_error(422, "invalid_input", "montant invalide", field="min_amount")
        if amount_currency is None:
            currencies = {
                row.customer_input.minimum_contract_value.currency
                for row in considered
                if row.customer_input.minimum_contract_value is not None
            }
            if len(currencies) == 1:
                amount_currency = next(iter(currencies))
            else:
                raise api_error(
                    422,
                    "invalid_input",
                    "une devise est requise avec le montant",
                    field="amount_currency",
                )
    try:
        check_filters(
            entitlements,
            {
                "target_icp_id": target_icp_id,
                "subdivision_code": subdivision_code,
                "min_amount": min_amount
                if min_amount is not None
                else offer_category or amount_currency,
            },
        )
    except FilterNotEntitled as error:
        raise api_error(
            403,
            error.code,
            str(error),
            filter=error.filter_name,
            required_level=error.required_level,
        ) from error
    values = {
        "target_icp_id": target_icp_id,
        "matching_revision": profile.matching_revision if profile is not None else 0,
        "offer_category": offer_category,
        "subdivision_code": subdivision_code,
        "min_amount": min_amount,
        "amount_currency": amount_currency,
        "offer_categories": offers,
    }
    tag = context_fingerprint(
        {
            **values,
            "account_id": account_id,
            "profiles": [
                (row.target_icp_id, row.matching_revision, row.updated_at) for row in considered
            ],
        }
    )
    return ConsultationScope(**values, context_tag=tag)
