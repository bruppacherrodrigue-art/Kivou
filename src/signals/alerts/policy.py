"""Quand un compte est dû, et ce que « prioritaire » veut dire.

Les cadences viennent du catalogue de facturation (§15)
──────────────────────────────────────────────────────
SPEC-013 expose déjà `alert_cadence` comme capacité de plan. Ce module la
rend opérationnelle sans la redéfinir : une seconde table de cadences
finirait par contredire la première.

« Prioritaire » n'est pas « temps réel » (§15)
─────────────────────────────────────────────
Scale est éligible **à chaque exécution du job**. C'est tout, et c'est déjà
utile. L'appeler « instantané » promettrait une architecture temps réel qui
n'existe pas — et une promesse de latence qu'aucun cron ne peut tenir.
"""

from __future__ import annotations

import datetime as dt

ALERT_POLICY_VERSION = "kivou-alerts-v0.1"

#: §20 — un e-mail borné. Au-delà, la lecture décroche et le reste attend le
#: cycle suivant plutôt que d'être noyé.
MAXIMUM_SIGNALS_PER_EMAIL = 10

#: §26 — l'écart minimal entre deux envois réussis, par cadence.
#: `priority` vaut zéro : éligible dès qu'il existe des signaux non envoyés.
MINIMUM_INTERVAL: dict[str, dt.timedelta | None] = {
    # `None` = jamais d'envoi automatique.
    "none": None,
    "weekly": dt.timedelta(days=7),
    "daily": dt.timedelta(days=1),
    "priority": dt.timedelta(0),
}

#: Les cadences qui déclenchent un envoi automatique.
SENDING_CADENCES: tuple[str, ...] = ("weekly", "daily", "priority")


def is_due(cadence: str, *, last_sent_at: dt.datetime | None, now: dt.datetime) -> bool:
    """Ce compte a-t-il droit à un envoi maintenant ?

    L'échéance se calcule sur le dernier envoi **réussi** : un échec SMTP ne
    doit pas consommer le tour du client, sinon une panne de deux jours lui
    ferait perdre deux digests.

    Une cadence inconnue ne déclenche rien — défaut fermé, comme partout
    ailleurs : un plan mal orthographié n'a pas à provoquer des e-mails.
    """
    interval = MINIMUM_INTERVAL.get(cadence)
    if interval is None:
        return False
    if last_sent_at is None:
        return True
    return now - last_sent_at >= interval
