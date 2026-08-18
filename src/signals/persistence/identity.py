"""Les identités stockées : de quel marché, pour quel client, parle-t-on ?

Trois clés, trois portées, et la troisième est celle qui compte pour le produit.

    event_key    une publication officielle          `EventRef.key()`
    award_key    un contrat attribué, pour un lot    identité de SPEC-005
    signal_key   ce marché, vu par CE client         award + ICP

Ce que `signal_key` ne contient **pas** est aussi important que ce qu'elle
contient : aucune version de moteur. Améliorer le Need Graph ne transforme pas
un signal en un autre signal — cela en produit une nouvelle révision, portée
par `materialized_signal.revision`. Mélanger les deux ferait réapparaître, à
chaque montée de version, la totalité du feed comme s'il était neuf.

C'est une divergence assumée avec `signals.research.signal100.signal_id`, qui
plie `match_policy_version` et `score_policy_version` dans son empreinte. Cette
fonction-là identifie une **mesure de banc** : deux versions de moteur y sont
deux observations distinctes, et c'est correct pour un banc. Ici on identifie
une **opportunité commerciale**, qui ne change pas de nature parce qu'un moteur
a changé de version.
"""

from __future__ import annotations

import hashlib

from signals.domain.awards import ContractAward
from signals.domain.events import PublicEvent

#: Séparateur des composantes d'une clé. `\x1f` (unit separator) ne peut pas
#: apparaître dans un identifiant publié, donc aucune concaténation ambiguë :
#: `("a:b", "c")` et `("a", "b:c")` ne peuvent pas produire la même empreinte.
_SEPARATOR = "\x1f"


def event_key(event: PublicEvent) -> str:
    """La clé d'une publication — celle que le domaine définit déjà."""
    return event.ref().key()


def _fingerprint(*parts: str | None) -> str:
    joined = _SEPARATOR.join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:40]


def award_key(award: ContractAward) -> str:
    """La clé d'un contrat attribué, pour un lot.

    Empreinte plutôt que concaténation lisible : les identifiants de lot des
    portails contiennent des caractères arbitraires, et une clé stockée doit
    rester bornée et sûre en URL.

    Elle est calculée même lorsque `source_identity()` rend `None` — c'est-à-dire
    quand la source ne publie pas d'identifiant de contrat. Ce cas signifie « je
    ne peux pas garantir l'unicité », pas « je ne peux pas stocker » ; la
    garantie reste portée par `SourceIdentity`, que la persistance conserve
    telle quelle à côté de la clé.
    """
    reference = award.event_ref
    return _fingerprint(
        reference.source_system,
        reference.source_notice_id,
        reference.notice_version,
        award.source_award_id,
        award.lot.identifier if award.lot else None,
    )


def signal_key(opportunity_key: str, *, target_icp_id: str) -> str:
    """La clé logique d'un signal : cette OPPORTUNITÉ, pour ce client.

    L'unité n'est pas la représentation source. Deux registres décrivant le même
    contrat produisent une seule opportunité, donc un seul signal — c'est la
    correction du closeout §2.

    `target_icp_id` désigne un `TargetICP` **possédé par un compte** et non un
    profil partagé entre clients (closeout §3). SPEC-011 introduira `account` et
    `target_icp(account_id, …)` sans que cette clé change de forme.
    """
    if not opportunity_key or not opportunity_key.strip():
        raise ValueError("un signal décrit une opportunité : `opportunity_key` est obligatoire")
    if not target_icp_id or not target_icp_id.strip():
        raise ValueError("un signal appartient à un TargetICP : `target_icp_id` est obligatoire")
    return _fingerprint(opportunity_key.strip(), target_icp_id.strip())
