"""Le statut unifié d'un signal pour CE compte : new | saved | ignored | contacted.

Dérivé de l'état courant `signal_feedback`, jamais stocké : l'action (contact)
l'emporte sur l'opinion (pertinence), qui l'emporte sur l'absence de jugement.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from signals.engagement.feedback import StoredFeedback

UNIFIED_STATUSES = ("new", "saved", "ignored", "contacted")
#: Le filtre par défaut de `GET /signals` : tout sauf `ignored`.
DEFAULT_LISTING_STATUSES = frozenset({"new", "saved", "contacted"})


def unified_status(feedback: StoredFeedback | None) -> str:
    """L'action (contact) l'emporte sur l'opinion, qui l'emporte sur l'absence de jugement."""
    if feedback is None:
        return "new"
    if feedback.contacted_at is not None:
        return "contacted"
    if feedback.relevance == "not_relevant":
        return "ignored"
    if feedback.relevance == "relevant":
        return "saved"
    return "new"


def status_resolver(feedback_by_key: Mapping[str, StoredFeedback]) -> Callable[[str], str]:
    """Une fonction `signal_key -> status`, fermée sur une lecture groupée."""
    return lambda signal_key: unified_status(feedback_by_key.get(signal_key))
