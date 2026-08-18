"""Le point d'entrée Stripe — le seul endpoint sans session Kivou.

    Il n'est pas « ouvert » : il est authentifié AUTREMENT (§15)
    ───────────────────────────────────────────────────────────
    Stripe ne porte pas de cookie de session et ne peut pas envoyer d'en-tête
    `Origin` : la protection CSRF du navigateur n'a aucun sens ici et lui
    appliquer la règle des origines bloquerait Stripe lui-même. L'autorité est
    la **signature** calculée sur le corps brut avec un secret partagé.

    Le corps brut est non négociable
    ────────────────────────────────
    Passer par le JSON analysé puis re-sérialisé produirait des octets
    différents — espaces, ordre des clés — et invaliderait une signature
    pourtant authentique. La route lit donc `await request.body()`.

Le secret vient de l'environnement et n'est jamais journalisé, jamais rendu,
jamais stocké.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from signals.api.dependencies import request_now
from signals.api.errors import api_error
from signals.billing import webhooks
from signals.billing.gateway import InvalidWebhookSignature, verify_event

router = APIRouter()

STRIPE_SIGNATURE_HEADER = "stripe-signature"


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, response: Response) -> dict[str, str]:
    """Vérifie, puis applique une fois. Une seconde livraison ne rejoue rien.

    Ce point d'entrée est `async` — le seul de l'application — parce qu'il doit
    lire le corps brut de la requête, ce que Starlette n'expose qu'en asynchrone.
    Le traitement qui suit reste synchrone, comme le reste du dépôt.
    """
    config = request.app.state.config
    gateway = getattr(request.app.state, "stripe_gateway", None)
    secret = config.stripe_webhook_secret
    if gateway is None or not secret:
        raise api_error(503, "billing_unavailable", "facturation non configurée")

    payload = await request.body()
    signature = request.headers.get(STRIPE_SIGNATURE_HEADER, "")
    try:
        event = verify_event(payload=payload, signature=signature, secret=secret)
    except InvalidWebhookSignature as error:
        # Le détail reste interne : dire POURQUOI la signature est invalide
        # aiderait qui essaie d'en forger une.
        raise api_error(400, "invalid_webhook_signature", "signature invalide") from error

    now = request_now(request)
    # L'enregistrement de l'événement et la transition partagent UNE transaction :
    # une transition à moitié appliquée n'est jamais confirmée, et Stripe pourra
    # relivrer l'événement (§18).
    with request.app.state.engine.begin() as connection:
        outcome = webhooks.handle_event(
            connection,
            gateway,
            event,
            payload=payload,
            expect_livemode=config.stripe_livemode,
            now=now,
        )

    if not outcome.accepted:
        response.status_code = 400
    return {"received": "true", "result": outcome.result}
