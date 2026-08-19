"""Deux sondes, et la différence entre les deux est tout l'intérêt.

    /health/live   — le processus répond-il ?
    /health/ready  — peut-il SERVIR ?

Pourquoi deux, et pourquoi elles ne doivent pas se ressembler
─────────────────────────────────────────────────────────────
Un superviseur de service redémarre ce qui n'est plus vivant, et retire du
trafic ce qui n'est pas prêt. Confondre les deux produit la panne classique :
la base devient injoignable, la sonde de vivacité échoue, l'orchestrateur
redémarre l'application — qui ne répare rien, puisque le problème est ailleurs,
et repart en boucle. `/health/live` ne touche donc JAMAIS la base.

Ce dont la disponibilité ne dépend pas (§15)
────────────────────────────────────────────
Ni Stripe, ni SMTP, ni SIMAP, ni BOAMP, ni DECP, ni TED. Kivou reste
parfaitement capable de servir un feed, une session et une page de facturation
quand une source publique est en panne ou qu'un fournisseur de paiement est
lent. Lier la disponibilité à un tiers reviendrait à laisser ce tiers décider de
notre disponibilité.

Ce qui ne sort jamais d'ici
───────────────────────────
Aucune URL de connexion, aucun identifiant, aucun nom d'hôte de base, aucune
trace d'exception. Une sonde de santé est un point d'entrée NON authentifié :
tout ce qu'elle rend est public. Elle dit ce qui ne va pas par un code, pas par
un message qui décrirait l'infrastructure.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request, Response

from signals.persistence.database import alembic_config, current_revision

router = APIRouter()


@router.get("/health/live")
def live() -> dict[str, str]:
    """Le processus est là et sert des requêtes. Rien d'autre n'est affirmé."""
    return {"status": "live"}


@router.get("/health/ready")
def ready(request: Request, response: Response) -> dict[str, Any]:
    """La base répond ET le schéma est celui qu'attend ce code.

    Le second point compte autant que le premier : une base joignable dont les
    migrations n'ont pas été jouées produirait des erreurs de colonne manquante
    au premier appel client. Mieux vaut ne pas recevoir de trafic.
    """
    engine = request.app.state.engine

    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    # BLE001 assumé : une sonde de disponibilité doit TOUJOURS répondre.
    # Restreindre au type attendu (`SQLAlchemyError`) laisserait remonter une
    # panne de résolution DNS ou de socket en 500, alors que la réponse juste
    # est « pas prêt ». Le détail part au journal, jamais dans le corps : cette
    # route n'est pas authentifiée.
    except Exception:  # noqa: BLE001
        response.status_code = 503
        return {"status": "not_ready", "reason": "database_unreachable"}

    try:
        applied = current_revision(engine)
        expected = _expected_revision(engine)
    # Même raison : lire la révision touche la base ET le dossier de migrations.
    # Aucun des deux ne doit pouvoir faire échouer la sonde autrement qu'en 503.
    except Exception:  # noqa: BLE001
        response.status_code = 503
        return {"status": "not_ready", "reason": "schema_unreadable"}

    if applied is None:
        response.status_code = 503
        return {"status": "not_ready", "reason": "migrations_not_applied"}

    if expected is not None and applied != expected:
        # Le déploiement a redémarré l'application sans jouer la migration, ou
        # l'a jouée vers une autre tête. Servir dans cet état donnerait des
        # erreurs SQL au premier client.
        response.status_code = 503
        return {
            "status": "not_ready",
            "reason": "schema_revision_mismatch",
            "applied_revision": applied,
            "expected_revision": expected,
        }

    # La révision appliquée est une information d'exploitation, pas un secret :
    # elle identifie une migration versionnée dans le dépôt.
    return {"status": "ready", "revision": applied}


def _expected_revision(engine: sa.Engine) -> str | None:
    """La tête des migrations telle que CE code la connaît.

    Rend `None` s'il y a plusieurs têtes — un état de dépôt anormal, qu'une
    sonde de santé n'a pas à trancher.
    """
    heads = ScriptDirectory.from_config(alembic_config(engine)).get_heads()
    return heads[0] if len(heads) == 1 else None
