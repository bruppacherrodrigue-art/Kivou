import { useEffect, useState } from 'react'
import { useI18n, interpolate } from '../i18n'
import { Badge, Callout, Card, SectionHeading, Skeleton } from '../components/Surfaces'
import { Button } from '../components/Button'
import { PlanGrid } from '../billing/PlanGrid'
import { billing } from '../api/endpoints'
import { ApiError } from '../api/client'
import { describeError } from '../api/errorCopy'
import type { BillingStatus, Currency, PlanCatalogue, PurchasablePlan } from '../api/types'
import styles from './Billing.module.css'

/* La page de facturation.
 *
 * Le frontend n'envoie QUE `{ plan, currency }`. Aucun `price_id`, aucun
 * coupon, aucun drapeau fondateur : le schéma `CheckoutRequest` interdit tout
 * champ supplémentaire, et surtout le montant n'est pas négociable depuis un
 * navigateur.
 *
 * La devise est un CHOIX EXPLICITE. La déduire de la langue ferait payer un
 * client suisse anglophone en euros — la langue et la devise sont deux
 * questions différentes, et le catalogue les traite comme telles (49 CHF **ou**
 * 49 EUR, pas une conversion).
 *
 * Kivou ne reconstruit aucun écran de gestion d'abonnement : moyen de paiement,
 * factures et résiliation vivent dans le portail du prestataire.
 */
export function Billing() {
  const { t, date } = useI18n()
  const [catalogue, setCatalogue] = useState<PlanCatalogue | null>(null)
  const [status, setStatus] = useState<BillingStatus | null>(null)
  const [currency, setCurrency] = useState<Currency>('chf')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [actionError, setActionError] = useState<unknown>(null)
  const [choosing, setChoosing] = useState<PurchasablePlan | null>(null)
  const [openingPortal, setOpeningPortal] = useState(false)

  useEffect(() => {
    let active = true
    Promise.all([billing.plans(), billing.status()])
      .then(([plans, billingStatus]) => {
        if (!active) return
        setCatalogue(plans)
        setStatus(billingStatus)
        // Une devise déjà facturée s'impose : on ne propose pas de changer la
        // devise d'un abonnement en cours depuis cet écran.
        if (billingStatus.currency === 'chf' || billingStatus.currency === 'eur') {
          setCurrency(billingStatus.currency)
        }
      })
      .catch((caught) => {
        if (active) setError(caught)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  async function startCheckout(plan: PurchasablePlan) {
    setActionError(null)
    setChoosing(plan)
    try {
      const session = await billing.checkout({ plan, currency })
      // La destination vient du backend, jamais d'une URL construite ici.
      window.location.assign(session.checkout_url)
    } catch (caught) {
      setActionError(caught)
      setChoosing(null)
    }
  }

  async function openPortal() {
    setActionError(null)
    setOpeningPortal(true)
    try {
      const session = await billing.portal()
      window.location.assign(session.portal_url)
    } catch (caught) {
      setActionError(caught)
      setOpeningPortal(false)
    }
  }

  if (loading) {
    return (
      <div className={styles.page}>
        <SectionHeading title={t.billing.title} lead={t.billing.lead} level={1} />
        <Card padding="lg">
          <Skeleton width="45%" height="1.5rem" />
        </Card>
      </div>
    )
  }

  if (error || !catalogue || !status) {
    const copy = describeError(error, t)
    return (
      <div className={styles.page}>
        <SectionHeading title={t.billing.title} lead={t.billing.lead} level={1} />
        <Callout tone="danger" title={copy.title} live>
          {copy.body}
        </Callout>
      </div>
    )
  }

  const isPaid = status.plan_code !== 'discovery'
  const actionCopy = actionError ? describeError(actionError, t) : null
  const expiresAt =
    actionError instanceof ApiError && typeof actionError.extra.expires_at === 'string'
      ? date(actionError.extra.expires_at)
      : null

  return (
    <div className={styles.page}>
      <SectionHeading title={t.billing.title} lead={t.billing.lead} level={1} />

      <Card padding="lg" as="section" className={styles.statusCard}>
        <div className={styles.statusHead}>
          <div>
            <p className={styles.statusLabel}>{t.billing.currentPlan}</p>
            <p className={styles.statusPlan}>{t.billing.plans[status.plan_code]}</p>
          </div>
          <Badge tone={isPaid ? 'positive' : 'neutral'}>
            {t.billing.status[
              (status.subscription_status ?? 'none') as keyof typeof t.billing.status
            ] ?? status.subscription_status}
          </Badge>
        </div>

        {status.current_period_end ? (
          <p className={styles.statusLine}>
            {interpolate(
              status.cancel_at_period_end ? t.billing.endsOn : t.billing.renewsOn,
              { date: date(status.current_period_end) ?? '' },
            )}
          </p>
        ) : null}

        {status.cancel_at_period_end ? (
          <Callout tone="warning">{t.billing.cancelAtPeriodEnd}</Callout>
        ) : null}

        {status.payment_issue ? (
          <Callout tone="danger">{t.billing.paymentIssue}</Callout>
        ) : null}

        {/* Un compte payant ne se voit PAS proposer un second paiement : il
            gère son abonnement dans le portail. */}
        {isPaid ? (
          <div className={styles.portal}>
            <p className={styles.statusLine}>{t.billing.manageLead}</p>
            <Button variant="secondary" loading={openingPortal} onClick={() => void openPortal()}>
              {t.billing.managePortal}
            </Button>
          </div>
        ) : null}
      </Card>

      {actionCopy ? (
        <Callout tone="danger" title={actionCopy.title} live>
          {actionCopy.body}
          {expiresAt ? (
            <> {interpolate(t.billing.errors.checkoutInProgressExpiry, { date: expiresAt })}</>
          ) : null}
        </Callout>
      ) : null}

      {!isPaid ? (
        <>
          <fieldset className={styles.currency}>
            <legend className={styles.currencyLegend}>{t.billing.currency}</legend>
            <p className={styles.currencyHelp}>{t.billing.currencyLead}</p>
            <div className={styles.currencyOptions}>
              {catalogue.currencies.map((code) => (
                <label
                  key={code}
                  className={`${styles.currencyOption} ${
                    currency === code ? styles.currencySelected : ''
                  }`}
                >
                  <input
                    type="radio"
                    name="kivou-currency"
                    className={styles.radio}
                    value={code}
                    checked={currency === code}
                    onChange={() => setCurrency(code)}
                  />
                  {code.toUpperCase()}
                </label>
              ))}
            </div>
          </fieldset>

          <section aria-label={t.billing.plansTitle}>
            <PlanGrid
              catalogue={catalogue}
              variant="app"
              currency={currency}
              currentPlan={status.plan_code}
              onChoose={(plan) => void startCheckout(plan)}
              choosingPlan={choosing}
              disabled={choosing !== null}
            />
          </section>
        </>
      ) : null}
    </div>
  )
}
