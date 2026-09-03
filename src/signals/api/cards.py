"""Le rendu d'une carte de signal DÉBLOQUÉ — partagé entre feed et fiche entreprise.

`GET /signals` et `GET /companies/{key}` montrent la MÊME carte pour un signal
débloqué : même présentation publiée, même enrichissement du vainqueur, même
statut. Dupliquer ce rendu ferait dériver silencieusement les deux surfaces —
exactement le défaut que ce module ferme.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from signals.card_intelligence.contracts import PublishedCardPresentation
from signals.companies.contracts import WinnerEnrichmentView
from signals.feed import query as feed_query
from signals.feed import view
from signals.persistence.schema import materialized_signal


def presentation_bindings_for_items(
    connection: sa.Connection, items: Any
) -> dict[str, tuple[int, int]]:
    """Reload only revision numbers absent from the legacy feed dataclass.

    The query is batched and receives only items whose access has already been
    granted.  Presentation lookup therefore never sees a locked signal key.
    """
    by_key = {item.signal.signal_key: item for item in items}
    if not by_key:
        return {}
    revisions = {
        row.signal_key: row.target_icp_revision
        for row in connection.execute(
            sa.select(
                materialized_signal.c.signal_key,
                materialized_signal.c.target_icp_revision,
            ).where(materialized_signal.c.signal_key.in_(tuple(by_key)))
        )
    }
    return {
        signal_key: (item.signal.revision, revisions[signal_key])
        for signal_key, item in by_key.items()
        if signal_key in revisions
    }


def render_unlocked_card(
    item: feed_query.FeedSignal,
    *,
    lang: str,
    presentation: PublishedCardPresentation | None,
    company_key: str | None,
    enrichment: WinnerEnrichmentView | None,
    status: str,
) -> dict[str, Any]:
    """The full card for a signal this account can already see (§16 unlocked).

    Extracted from `routes_signals._render`'s unlocked branch so a second
    surface (the company profile's `signals`) cannot drift from the feed's
    notion of what an unlocked card contains.
    """
    card = view.feed_item(item, lang=lang, presentation=presentation)
    card["locked"] = False
    card["status"] = status
    if company_key is not None:
        card["company_key"] = company_key
    if enrichment is not None:
        card["winner_enrichment"] = enrichment.model_dump(mode="json")
        if enrichment.official_name is not None:
            card["company"]["name"] = enrichment.official_name
    return card


__all__ = ["presentation_bindings_for_items", "render_unlocked_card"]
