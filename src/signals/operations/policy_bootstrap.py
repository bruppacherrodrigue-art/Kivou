"""Écriture explicite du tout premier contrôle Policy d'un environnement."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy.engine import Engine

from signals.operations.contracts import canonical_fingerprint
from signals.operations.qa_policy_window import RUNTIME_COMMANDS
from signals.policy.contracts import (
    AutonomyMode,
    PolicyControlSnapshot,
    PolicyControlUnavailable,
)
from signals.policy.store import PolicyStore


class PolicyBootstrapError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(f"policy bootstrap error: {code}")
        self.code = code


def bootstrap_policy_control(
    engine: Engine,
    *,
    at: dt.datetime,
    actor_ref: str,
    reason_code: str,
    daily_cost_cap: Decimal,
    country: str,
    language: str,
    wedge: str,
) -> PolicyControlSnapshot:
    """Pose la première autorité Policy exécutable de l'environnement.

    Décidé le 2026-09-01 : le mode est ASSISTED, pas SHADOW.
    `evaluator.py:296` rend `executable` inconditionnellement faux sous
    SHADOW, quelle que soit la classe de risque de la commande — l'ancien
    amorçage SHADOW (+ `shadow_target_mode=ASSISTED`) arrêtait donc chaque
    cycle à sa toute première étape évaluée par la Policy, sans jamais
    produire de mesure. `shadow_target_mode` vaut maintenant None : le
    contrat l'interdit hors SHADOW. La lecture seule et le coupe-circuit
    sont désarmés ; le plafond de volume quotidien vaut zéro.

    Ce n'est PAS pour autant un levier d'envoi. Trois des onze commandes du
    cycle — `prepare_campaign`, `schedule_campaign`,
    `execute_provider_operations` — sont COMMERCIAL_MUTATION ; les huit
    autres restent READ_ONLY ou PREPARATORY (le cycle entier n'est donc pas
    PREPARATORY, contrairement à ce que ce docstring affirmait). Rien
    n'atteint un fournisseur ou une boîte de réception : cinq gardes
    indépendants retiennent l'envoi, aucun d'eux porté par ce seul contrôle.

    1. `PROVIDER_HANDOFF` reste `WAITING` inconditionnel tant que le cycle
       n'a pas reçu `--allow-qa-provider-mutations` (`runner.py`,
       `registry.py`) ;
    2. le CLI refuse ce drapeau dès que l'environnement est PRODUCTION
       (`cli.py`) ;
    3. `daily_volume_cap=0` fait échouer `schedule_campaign` et
       `execute_provider_operations` en BUDGET_EXCEEDED — ce sont les deux
       seules commandes du registre portant `uses_volume=True` ;
    4. sous ASSISTED, toute commande COMMERCIAL_MUTATION exige un accord
       humain à usage unique (`evaluator.py`), absent d'un cycle automatisé ;
    5. la composition de production ne construit aucun détournement de
       destinataire.
    """

    if at.tzinfo is None or at.utcoffset() is None:
        raise PolicyBootstrapError("TIMESTAMP_NOT_AWARE")
    if country not in {"CH", "FR"} or language not in {"fr", "en"} or not wedge:
        raise PolicyBootstrapError("SCOPE_INVALID")
    if not daily_cost_cap.is_finite() or daily_cost_cap <= 0:
        raise PolicyBootstrapError("COST_CAP_INVALID")
    store = PolicyStore(engine)
    try:
        store.get_latest_control()
    except PolicyControlUnavailable:
        pass
    else:
        raise PolicyBootstrapError("CONTROL_ALREADY_EXISTS")
    observed_at = at.astimezone(dt.UTC)
    fingerprint = canonical_fingerprint(
        "acquisition-policy-bootstrap:v1",
        {
            "control_revision": 1,
            "autonomy_mode": AutonomyMode.ASSISTED.value,
            "shadow_target_mode": None,
            "country": country,
            "language": language,
            "wedge": wedge,
            "currency": "CHF",
            "daily_cost_cap": str(daily_cost_cap),
            "effective_at": observed_at.isoformat(),
            "actor_ref": actor_ref,
            "reason_codes": (reason_code,),
        },
    )
    try:
        control = PolicyControlSnapshot(
            policy_snapshot_id=fingerprint,
            control_revision=1,
            autonomy_mode=AutonomyMode.ASSISTED,
            shadow_target_mode=None,
            read_only=False,
            kill_switch=False,
            allowed_commands=RUNTIME_COMMANDS,
            allowed_countries=(country,),
            allowed_languages=(language,),
            allowed_wedges=(wedge,),
            currency="CHF",
            daily_cost_cap=daily_cost_cap,
            daily_volume_cap=0,
            effective_at=observed_at,
            snapshot_fingerprint=fingerprint,
            created_at=observed_at,
            created_by_actor_type="HUMAN",
            created_by_actor_ref=actor_ref,
            reason_codes=(reason_code,),
        )
    except (ValidationError, ValueError):
        raise PolicyBootstrapError("CONTROL_INVALID") from None
    store.append_control(control)
    return control


__all__ = ["PolicyBootstrapError", "bootstrap_policy_control"]
