"""Fabriques partagées pour les tests du vérificateur commercial (SPEC-009A).

Une vue aveugle synthétique, façonnable trait par trait. Elle a exactement la
forme produite par SPEC-009 — c'est ce qui garantit que ces tests portent sur le
vrai contrat d'entrée, et pas sur une structure inventée pour l'occasion.
"""

from __future__ import annotations

from typing import Any

import pytest


def make_blind(**overrides: Any) -> dict[str, Any]:
    """Une vue aveugle plausible et complète, modifiable par sections.

    Les surcharges sont fusionnées section par section : un test qui ne veut
    changer que le timing n'a pas à réécrire le contrat entier.
    """
    blind: dict[str, Any] = {
        "signal_id": "a" * 64,
        "source": "simap",
        "publication_date": "2026-08-10",
        "source_url": "https://www.simap.ch/api/publications/v1/project/p/publication-details/q",
        "winner": {
            "status": "identified",
            "parties": [
                {
                    "name": None,
                    "is_group": False,
                    "members": [
                        {
                            "legal_name": "Bauunternehmung Meier AG",
                            "country": "CH",
                            "identifiers": [],
                            "address": "Industriestrasse 4, 3000 Bern",
                            "website": None,
                            "role": "sole",
                        }
                    ],
                }
            ],
        },
        "contract": {
            "title": "Travaux de gros oeuvre pour la nouvelle ecole primaire",
            "lot_title": None,
            "contract_reference": "LOT-01",
            "description": (
                "Le marche porte sur les travaux de gros oeuvre, les fondations et la "
                "structure porteuse du batiment scolaire, avec une duree de chantier de "
                "dix-huit mois et des interventions sur un site en exploitation."
            ),
            "cpv_main": "45214200",
            "cpv_additional": [],
            "value": {"amount": "4200000", "currency": "CHF", "vat_category": None},
            "place_of_performance": {"country": "CH", "locality": "Bern"},
            "buyers": [{"legal_name": "Stadt Bern", "country": "CH"}],
        },
        "contract_understanding": {
            "contract_type": "construction",
            "sector": "education",
            "object_summary": "Travaux de gros oeuvre pour une ecole primaire a Bern",
            "characteristics": ["chantier de longue duree"],
            "facts": {"amount": "4200000 CHF"},
            "buyer_country": "CH",
            "place_of_performance": {"country": "CH", "locality": "Bern"},
            "timing": {
                "published_at": "2026-08-10",
                "award_date": "2026-08-01",
                "contract_signature_date": None,
                "contract_start_date": "2026-09-15",
                "contract_end_date": "2028-03-15",
                "duration_value": 18,
                "duration_unit": "month",
                "days_between_award_and_start": 45,
                "contract_span_days": 547,
                "derived_from": ["award", "duration"],
            },
        },
        "derived_needs": [
            {
                "category": "workforce_capacity",
                "statement": "Un besoin de capacite en personnel de chantier peut devenir pertinent.",
                "reasoning": (
                    "Un chantier de gros oeuvre de dix-huit mois mobilise des equipes "
                    "que l'attributaire peut ne pas avoir entierement disponibles."
                ),
                "timing": "near_term",
                "externalisability": "high",
                "confidence": "medium",
                "evidence_refs": [],
                "supporting_facts": [],
                "source_mode": "metadata_fallback",
            }
        ],
        "icp": {
            "icp_id": "icp-staffing-ch",
            "name": "Agence d'interim BTP — Suisse",
            "offer_summary": "Mise a disposition de personnel qualifie pour chantiers.",
            "primary_need_categories": ["workforce_capacity"],
            "secondary_need_categories": ["specialist_subcontracting"],
            "territories": [{"country": "CH", "subdivision_code": None}],
            "geography_basis": "place_of_performance",
            "geography_policy": "required",
            "included_contract_types": [],
            "excluded_contract_types": ["it_digital", "research"],
            "included_sectors": [],
            "excluded_sectors": [],
            "value_thresholds": [
                {"currency": "CHF", "minimum_amount": 250000.0, "maximum_amount": None}
            ],
            "maximum_signal_age_days": 90,
            "preferred_timings": ["immediate", "near_term", "recurring"],
        },
        "evidence_refs": [
            {
                "source_system": "simap",
                "source_kind": "publication_field",
                "source_notice_id": "q",
                "source_procedure_id": "p",
                "source_url": "https://www.simap.ch/api/publications/v1/project/p/x/q",
                "path": "procurement.cpvCode.code",
                "raw_value": "45214200",
                "excerpt": None,
            },
            {
                "source_system": "simap",
                "source_kind": "publication_field",
                "source_notice_id": "q",
                "source_procedure_id": "p",
                "source_url": "https://www.simap.ch/api/publications/v1/project/p/x/q",
                "path": "procurement.description",
                "raw_value": None,
                "excerpt": "Travaux de gros oeuvre",
            },
        ],
        "source_mode": "metadata_fallback",
        "disclosure": (
            "Need inferred from public award information. "
            "No validated execution requirement was available."
        ),
    }

    for section, value in overrides.items():
        if isinstance(value, dict) and isinstance(blind.get(section), dict):
            merged = {**blind[section], **value}
            # Le timing est imbriqué : le surcharger partiellement doit rester possible.
            if "timing" in value and isinstance(value["timing"], dict):
                merged["timing"] = {**blind[section]["timing"], **value["timing"]}
            blind[section] = merged
        else:
            blind[section] = value
    return blind


@pytest.fixture
def blind() -> dict[str, Any]:
    return make_blind()
