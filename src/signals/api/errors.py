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
    "not_authenticated",
    "csrf_origin_rejected",
    "invalid_input",
    "signal_not_found",
)


def api_error(status_code: int, code: str, message: str, **extra: Any) -> HTTPException:
    """Une erreur HTTP portant un code stable. Le message reste générique."""
    if code not in ERROR_CODES:  # pragma: no cover - garde-fou de développement
        raise AssertionError(f"code d'erreur non déclaré : {code}")
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message, **extra}
    )
