"""La taxonomie des pannes du vérificateur (SPEC-009A §25).

Une panne n'est **jamais** un rejet du signal. Le résultat opérationnel reste
`HIDE` — un feed precision-first ne montre pas ce qu'il n'a pas pu vérifier —
mais le diagnostic technique doit rester distinct du jugement commercial, sinon
une coupure réseau se lirait plus tard comme « le moteur produit des signaux
faibles ».
"""

from __future__ import annotations

#: Les natures de panne nommées par §25. `validation_failure` naît chez nous,
#: pas chez le fournisseur : c'est notre validateur déterministe qui refuse.
FAILURE_KINDS = (
    "api_credit_failure",
    "api_rate_limit",
    "transport_failure",
    "provider_failure",
    "schema_failure",
    "validation_failure",
    "unauthorized",
    "client_error",
)


class CredentialMissing(RuntimeError):
    """Aucune credential configurée. On ne devine pas, on ne code pas en dur."""


class VerificationFailure(RuntimeError):
    """Une panne nommée, remontée quand l'appelant doit décider d'arrêter."""

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


def api_failure_kind(status_code: int) -> str:
    """Nomme une panne HTTP selon la taxonomie §25."""
    if status_code in (401, 403):
        return "unauthorized"
    if status_code == 402:
        return "api_credit_failure"
    if status_code == 429:
        return "api_rate_limit"
    if status_code >= 500:
        return "provider_failure"
    return "client_error"
