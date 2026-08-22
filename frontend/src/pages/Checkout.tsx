import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n, interpolate } from '../i18n'
import { Callout, Card } from '../components/Surfaces'
import { Button, ButtonLink } from '../components/Button'
import { PaymentConfirmedIllustration } from '../assets/Illustrations'
import { clearCheckoutIntent, readCheckoutIntent } from '../billing/checkoutIntent'
import { billing } from '../api/endpoints'
import type { BillingStatus } from '../api/types'
import styles from './Checkout.module.css'

/* Le retour de paiement.
 *
 * RÈGLE CENTRALE : cette page n'accorde AUCUN accès.
 *
 * Être arrivé ici ne prouve rien — l'URL de retour est une simple redirection,
 * et n'importe qui peut l'ouvrir directement. La seule autorité est l'état de
 * facturation du compte, qui ne bascule que lorsque le webhook Stripe a été
 * reçu et traité côté serveur. La page interroge donc `/billing/status`
 * jusqu'à ce que le plan change, et n'écrit jamais rien.
 *
 * L'attente est BORNÉE. Un sondage infini masquerait une panne de webhook
 * derrière une animation, et laisserait le client devant un écran qui tourne
 * sans rien lui dire. Au terme du délai, la page explique ce qui se passe et
 * rend la main.
 *
 * Ce que la page annonce, et ce qu'elle se garde d'annoncer
 * ────────────────────────────────────────────────────────
 * Elle dit « accès payant actif », jamais « paiement confirmé ». La nuance
 * n'est pas cosmétique : n'importe qui peut ouvrir cette adresse, et un client
 * payant depuis des semaines peut la rouvrir à la main. Affirmer un paiement
 * qui vient d'avoir lieu serait alors faux. Ce que la page constate, elle le
 * tient du serveur : des droits payants sont ouverts.
 */

const POLL_INTERVAL_MS = 2500
const POLL_TIMEOUT_MS = 45_000

export function CheckoutSuccess() {
  const { t } = useI18n()
  const [status, setStatus] = useState<BillingStatus | null>(null)
  /* Le signal qui a déclenché l'achat, lu UNE fois au montage. Il ne prouve
   * rien et n'ouvre rien : il ne sert qu'à savoir où ramener le client une fois
   * que le serveur, lui, a confirmé. Si le détail répond ensuite `locked`,
   * c'est `locked` qui s'affiche. */
  const [intent] = useState(() => readCheckoutIntent())
  const [timedOut, setTimedOut] = useState(false)
  const startedAt = useRef(Date.now())
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const confirmed = status !== null && status.plan_code !== 'discovery'

  const poll = useCallback(async () => {
    try {
      const next = await billing.status()
      setStatus(next)
      if (next.plan_code !== 'discovery') return
    } catch {
      // Une lecture qui échoue ne conclut rien : on retente jusqu'au délai.
    }

    if (Date.now() - startedAt.current >= POLL_TIMEOUT_MS) {
      setTimedOut(true)
      return
    }
    timer.current = setTimeout(() => void poll(), POLL_INTERVAL_MS)
  }, [])

  useEffect(() => {
    void poll()
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [poll])

  /* L'intention est consommée dès que le serveur confirme, pas au clic.
   * La lier au CTA laissait le stockage sale dès que le client choisissait
   * « Voir tous mes signaux » — ou fermait simplement l'onglet — et la clé
   * ressurgissait sur une page de succès ultérieure. `intent` reste en état
   * React pour CE rendu : ce qui est effacé est le stockage, pas l'affichage. */
  useEffect(() => {
    if (confirmed) clearCheckoutIntent()
  }, [confirmed])

  function refresh() {
    startedAt.current = Date.now()
    setTimedOut(false)
    void poll()
  }

  return (
    <main className={styles.page} id="kivou-main">
      <Card padding="lg" className={styles.card}>
        <PaymentConfirmedIllustration className={styles.illustration} />

        <h1 className={styles.title}>
          {confirmed ? t.checkout.successTitle : t.checkout.successPending}
        </h1>

        {/* UNE seule région live, qui ne se démonte jamais.
         *
         * Elle vivait auparavant dans la branche « en attente ». Au moment où
         * l'accès devenait actif, ce nœud disparaissait et le texte de
         * confirmation apparaissait ailleurs : un lecteur d'écran n'annonce
         * pas le contenu d'une région qui vient de naître, seulement le
         * changement d'une région qui existait déjà. L'annonce était donc
         * perdue précisément à l'instant qui compte. */}
        <p className={styles.body} role="status" aria-live="polite">
          {confirmed
            ? interpolate(t.checkout.successBody, {
                plan: t.billing.plans[status.plan_code],
              })
            : timedOut
              ? t.checkout.successTimeout
              : t.checkout.successPendingBody}
        </p>

        <div className={styles.actions}>
          {confirmed ? (
            intent !== null ? (
              <>
                <ButtonLink to={`/app/signals/${encodeURIComponent(intent)}`} size="lg">
                  {t.checkout.returnToSignal}
                </ButtonLink>
                <ButtonLink to="/app/signals" variant="secondary" size="lg">
                  {t.checkout.seeAllSignals}
                </ButtonLink>
              </>
            ) : (
              <ButtonLink to="/app/signals" size="lg">
                {t.checkout.goToSignals}
              </ButtonLink>
            )
          ) : (
            <Button variant="secondary" size="lg" onClick={refresh} disabled={!timedOut}>
              {t.checkout.refresh}
            </Button>
          )}
          <ButtonLink to="/app/billing" variant="quiet">
            {t.checkout.seeBilling}
          </ButtonLink>
        </div>
      </Card>
    </main>
  )
}

/** Le retour depuis le parcours de paiement.
 *
 *  Cette page ne SAIT presque rien, et sa copy s'arrête là.
 *
 *  C'est une URL de retour : n'importe qui peut l'ouvrir, à n'importe quel
 *  moment, y compris un client payant depuis des mois. Elle ne reçoit rien de
 *  Stripe et n'interroge rien. Elle ne peut donc affirmer ni qu'un paiement a
 *  été interrompu, ni qu'aucun débit n'a eu lieu, ni que l'offre n'a pas
 *  changé — trois assertions qu'elle portait pourtant.
 *
 *  Ce qu'elle sait : le client est revenu, et elle-même ne modifie rien. Pour
 *  l'état réel, elle renvoie à la facturation, qui l'interroge vraiment. */
export function CheckoutCancel() {
  const { t } = useI18n()

  /* Le parcours d'achat est abandonné : l'intention n'a plus d'objet. La
   * garder ferait réapparaître « revenir à ce signal » après un achat
   * ultérieur, sans rapport avec celui-ci. */
  useEffect(() => clearCheckoutIntent(), [])

  return (
    <main className={styles.page} id="kivou-main">
      <Card padding="lg" className={styles.card}>
        <h1 className={styles.title}>{t.checkout.cancelTitle}</h1>
        <Callout tone="info">{t.checkout.cancelBody}</Callout>

        <div className={styles.actions}>
          {/* La facturation est la seule surface qui interroge réellement
              l'état de l'abonnement — et elle sait, elle, quoi proposer. */}
          <ButtonLink to="/app/billing" size="lg">
            {t.checkout.seeBilling}
          </ButtonLink>
          <ButtonLink to="/app/signals" variant="secondary" size="lg">
            {t.checkout.backToSignals}
          </ButtonLink>
        </div>
      </Card>
    </main>
  )
}
