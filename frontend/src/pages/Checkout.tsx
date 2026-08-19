import { useCallback, useEffect, useRef, useState } from 'react'
import { useI18n, interpolate } from '../i18n'
import { Callout, Card } from '../components/Surfaces'
import { Button, ButtonLink } from '../components/Button'
import { PaymentConfirmedIllustration } from '../assets/Illustrations'
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
 */

const POLL_INTERVAL_MS = 2500
const POLL_TIMEOUT_MS = 45_000

export function CheckoutSuccess() {
  const { t } = useI18n()
  const [status, setStatus] = useState<BillingStatus | null>(null)
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

  function refresh() {
    startedAt.current = Date.now()
    setTimedOut(false)
    void poll()
  }

  return (
    <main className={styles.page} id="kivou-main">
      <Card padding="lg" className={styles.card}>
        <PaymentConfirmedIllustration className={styles.illustration} />

        {confirmed ? (
          <>
            <h1 className={styles.title}>{t.checkout.successTitle}</h1>
            <p className={styles.body}>
              {interpolate(t.checkout.successBody, {
                plan: t.billing.plans[status.plan_code],
              })}
            </p>
          </>
        ) : (
          <>
            <h1 className={styles.title}>{t.checkout.successPending}</h1>
            {/* `aria-live` : le passage de « en cours » à « confirmé » est
                annoncé sans qu'il faille relire la page. */}
            <p className={styles.body} role="status" aria-live="polite">
              {timedOut ? t.checkout.successTimeout : t.checkout.successPendingBody}
            </p>
          </>
        )}

        <div className={styles.actions}>
          {confirmed ? (
            <ButtonLink to="/app/signals" size="lg">
              {t.checkout.goToSignals}
            </ButtonLink>
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

/** L'annulation.
 *
 *  Aucune mutation, et surtout aucun message d'échec : quitter un paiement
 *  n'est pas un refus de carte, et le dire ainsi inquiéterait pour rien. */
export function CheckoutCancel() {
  const { t } = useI18n()

  return (
    <main className={styles.page} id="kivou-main">
      <Card padding="lg" className={styles.card}>
        <h1 className={styles.title}>{t.checkout.cancelTitle}</h1>
        <Callout tone="info">{t.checkout.cancelBody}</Callout>

        <div className={styles.actions}>
          <ButtonLink to="/app/billing" size="lg">
            {t.checkout.backToPlans}
          </ButtonLink>
          <ButtonLink to="/app/signals" variant="secondary" size="lg">
            {t.checkout.backToSignals}
          </ButtonLink>
        </div>
      </Card>
    </main>
  )
}
