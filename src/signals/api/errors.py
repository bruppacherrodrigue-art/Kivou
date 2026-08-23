"""Codes d'erreur stables, et ce qu'ils taisent.

Un code machine ne change pas quand la formulation change : c'est lui que le
frontend teste. Le message accompagne, il n'est jamais la donnée.

    Ce qui ne sort jamais
    ─────────────────────
    Erreurs SQL, détails d'empreinte, jetons, existence d'un compte lors d'une
    connexion ou d'une réinitialisation, existence d'une ressource appartenant à
    un autre compte. Une erreur d'autorisation qui distingue « interdit » de
    « inexistant » est un oracle d'énumération.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

ERROR_CODES: tuple[str, ...] = (
    "email_already_used",
    "invalid_credentials",
    "unsupported_locale",
    "invalid_reset_token",
    "target_icp_not_found",
    "territory_limit_exceeded",
    "not_authenticated",
    "csrf_origin_rejected",
    "invalid_input",
    "signal_not_found",
    # SPEC-013 — facturation
    "billing_unavailable",
    "invalid_webhook_signature",
    "unknown_plan",
    "plan_not_purchasable",
    "price_not_configured",
    "already_subscribed",
    "no_billing_customer",
    "stripe_mode_mismatch",
    "founding_not_available",
    "filter_not_entitled",
    "billing_error",
    "billing_subscription_conflict",
    "checkout_in_progress",
    # P0-03F — l'appel Stripe de création de session, et ses deux issues.
    "checkout_rejected",
    "checkout_unavailable",
    # SPEC-014 — retour client et notifications
    "invalid_feedback",
    "signal_not_accessible",
    "invalid_notification_email",
    # SPEC-026 — provider-specific, authenticated transport ingress.
    "instantly_webhook_unavailable",
    "instantly_json_required",
    "invalid_instantly_webhook_secret",
    "instantly_webhook_too_large",
    "invalid_instantly_json",
    "invalid_instantly_event",
    # SPEC-028 — a bad opaque token is indistinguishable from a missing link.
    "attribution_not_found",
    # SPEC-030 — internal business information is default-denied.
    "cockpit_forbidden",
)


def api_error(status_code: int, code: str, message: str, **extra: Any) -> HTTPException:
    """Une erreur HTTP portant un code stable. Le message reste générique."""
    if code not in ERROR_CODES:  # pragma: no cover - garde-fou de développement
        raise AssertionError(f"code d'erreur non déclaré : {code}")
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message, **extra}
    )
