import { useCallback, useMemo, useRef, useState } from 'react'
import { Check, LockKeyhole, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { billing } from '../../api/endpoints'
import { describeError } from '../../api/errorCopy'
import type { CataloguePlan, PurchasablePlan } from '../../api/types'
import { useCurrentUser } from '../../auth/SessionProvider'
import { saveCheckoutReturn, validateCheckoutReturn, type CheckoutReturnIntent } from '../../billing/checkoutIntent'
import { secureBillingDestination } from '../../billing/destination'
import { SUBSCRIPTION_CURRENCY, subscriptionPrice } from '../../billing/subscriptionPricing'
import { interpolate, useI18n } from '../../i18n'
import { useResource } from '../../presentation/dashboard/resources'
import { DetailFrame } from './DetailFrame'
import styles from '../Prospecting.module.css'

const COPY = {
  fr: {
    locked: 'SIGNAL VERROUILLÉ',
    title: 'Continuez votre prospection',
    exhausted: 'Vous avez utilisé vos {count} signaux Découverte. Passez à un abonnement pour accéder aux prochaines opportunités et à leurs preuves.',
    available: 'Votre accès Découverte ne couvre pas ce signal. Passez à un abonnement pour accéder aux prochaines opportunités et à leurs preuves.',
    loading: 'Chargement des offres…', unavailable: 'Les offres ne sont pas disponibles pour le moment.', retry: 'Réessayer',
    manage: 'Gérer ma facturation', recommended: 'Recommandé', perMonth: '/ mois',
    opening: 'Ouverture du paiement…', choose: 'Choisir {plan} — {price}/mois',
    essential: 'Pour prospecter un marché précis.', pro: 'Pour suivre plusieurs marchés et agir plus vite.',
    oneProfile: '1 profil cible', profiles: '{count} profils cibles', oneTerritory: '1 territoire', territories: 'Plusieurs territoires',
    signalsOne: 'Signaux correspondant à votre profil', signalsOther: 'Signaux correspondant à vos profils',
    evidence: 'Preuves et sources complètes', weekly: 'Alertes hebdomadaires', daily: 'Alertes quotidiennes', priority: 'Alertes prioritaires',
    history: '{count} jours d’historique', advanced: 'Filtres avancés', reassurance: 'Paiement sécurisé · Abonnement mensuel · Résiliation depuis votre espace de facturation',
    continue: 'Continuer avec Découverte', invalidDestination: 'La destination de paiement reçue est invalide. Réessayez dans quelques instants.',
  },
  en: {
    locked: 'LOCKED SIGNAL', title: 'Keep prospecting',
    exhausted: 'You have used your {count} Discovery signals. Subscribe to access the next signals and their evidence.',
    available: 'Your Discovery access does not cover this signal. Subscribe to access the next signals and their evidence.',
    loading: 'Loading plans…', unavailable: 'Plans are temporarily unavailable.', retry: 'Retry', manage: 'Manage billing', recommended: 'Recommended', perMonth: '/ month',
    opening: 'Opening checkout…', choose: 'Choose {plan} — {price}/month',
    essential: 'For prospecting one specific contract.', pro: 'For tracking several markets and acting faster.',
    oneProfile: '1 target profile', profiles: '{count} target profiles', oneTerritory: '1 territory', territories: 'Multiple territories',
    signalsOne: 'Signals matching your profile', signalsOther: 'Signals matching your profiles', evidence: 'Complete evidence and sources', weekly: 'Weekly alerts', daily: 'Daily alerts', priority: 'Priority alerts',
    history: '{count} days of history', advanced: 'Advanced filters', reassurance: 'Secure payment · Monthly subscription · Cancel from your billing portal',
    continue: 'Continue with Discovery', invalidDestination: 'The payment destination is invalid. Try again in a moment.',
  },
} as const

export function UpgradeDialog(props: { onClose: () => void; intent: CheckoutReturnIntent; upgradeTo?: string[] }) {
  const me = useCurrentUser()
  return <AccountUpgrade key={me.account_id} {...props} accountId={me.account_id} />
}

function planName(code: string) {
  if (code === 'essential') return 'Essential'
  return 'Pro'
}

function benefits(plan: CataloguePlan, copy: typeof COPY.fr | typeof COPY.en) {
  const e = plan.entitlements
  const rows = [
    e.max_active_icps === 1 ? copy.oneProfile : interpolate(copy.profiles, { count: e.max_active_icps }),
    e.territory_mode === 'single' ? copy.oneTerritory : copy.territories,
    e.max_active_icps === 1 ? copy.signalsOne : copy.signalsOther,
  ]
  if (e.evidence_access) rows.push(copy.evidence)
  if (e.alert_cadence === 'weekly') rows.push(copy.weekly)
  if (e.alert_cadence === 'daily') rows.push(copy.daily)
  if (e.alert_cadence === 'priority') rows.push(copy.priority)
  if (e.history_days && e.history_days > 0) rows.push(interpolate(copy.history, { count: e.history_days }))
  if (e.filter_level === 'advanced') rows.push(copy.advanced)
  return rows
}

function AccountUpgrade({ onClose, intent, accountId, upgradeTo }: { onClose: () => void; intent: CheckoutReturnIntent; accountId: string; upgradeTo?: string[] }) {
  const { locale, money, t } = useI18n()
  const copy = COPY[locale]
  const [submitting, setSubmitting] = useState<string | null>(null)
  const [checkoutError, setCheckoutError] = useState<unknown>(null)
  const [destinationError, setDestinationError] = useState(false)
  const busyRef = useRef(false)
  const load = useCallback(async () => {
    const [catalogue, status] = await Promise.all([billing.plans(), billing.status()])
    return { catalogue, status }
  }, [])
  const resource = useResource(load)
  const target = validateCheckoutReturn(intent)
  const plans = useMemo(() => resource.data?.catalogue.plans.filter((plan) => {
    if (plan.plan_code !== 'essential' && plan.plan_code !== 'pro') return false
    if (!plan.purchasable || !subscriptionPrice(plan)) return false
    return !upgradeTo || upgradeTo.includes(plan.plan_code)
  }) ?? [], [resource.data, upgradeTo])
  const canChoose = resource.data?.status.billing_action === 'choose_plan'
  const exhausted = resource.data?.status.discovery.remaining_slots === 0
  const discoveryCount = resource.data?.status.discovery.limit ?? 3
  const errorCopy = checkoutError ? describeError(checkoutError, t) : null

  async function startCheckout(plan: CataloguePlan) {
    const price = subscriptionPrice(plan)
    if (busyRef.current || !target || !price || !canChoose || !plan.purchasable) return
    busyRef.current = true
    setSubmitting(plan.plan_code)
    setCheckoutError(null)
    setDestinationError(false)
    try {
      const session = await billing.checkout({ plan: plan.plan_code as PurchasablePlan, currency: SUBSCRIPTION_CURRENCY })
      const destination = secureBillingDestination(session.checkout_url)
      if (!destination) {
        setDestinationError(true)
        return
      }
      saveCheckoutReturn(accountId, target)
      window.location.assign(destination)
    } catch (error) {
      setCheckoutError(error)
    } finally {
      busyRef.current = false
      setSubmitting(null)
    }
  }

  return <DetailFrame title={copy.locked} badge={<span aria-hidden="true" />} onClose={onClose} commercial planCount={plans.length}>
    <div className={styles.paywallIntro}>
      <span className={styles.paywallEyebrow}><LockKeyhole aria-hidden="true" />{copy.locked}</span>
      <h2>{copy.title}</h2>
      <p>{interpolate(exhausted ? copy.exhausted : copy.available, { count: discoveryCount })}</p>
    </div>
    {resource.loading ? <p role="status" className={styles.paywallStatus}>{copy.loading}</p>
      : resource.error ? <div className={styles.paywallStatus}><p role="alert" className={styles.error}>{copy.unavailable}</p><button className={styles.button} onClick={() => void resource.retry()}>{copy.retry}</button></div>
        : !canChoose ? <div className={styles.paywallStatus}><Link className={styles.primary} to="/app/billing">{copy.manage}</Link></div>
          : plans.length === 0 ? <p role="status" className={styles.paywallStatus}>{copy.unavailable}</p>
          : <div className={styles.paywallPlans} data-count={plans.length}>{plans.map((plan) => {
            const price = subscriptionPrice(plan)!
            const name = planName(plan.plan_code)
            const formattedPrice = money(price.amount_minor_units, price.currency.toUpperCase())
            const description = plan.plan_code === 'essential' ? copy.essential : copy.pro
            return <section className={`${styles.paywallPlan} ${plan.recommended ? styles.paywallRecommended : ''}`} key={plan.plan_code}>
              <div className={styles.paywallPlanHead}><h3>{name}</h3>{plan.recommended && <span className={styles.paywallBadge}>{copy.recommended}</span>}</div>
              <p className={styles.paywallPrice}><strong>{formattedPrice}</strong> <span>{copy.perMonth}</span></p>
              <p className={styles.paywallDescription}>{description}</p>
              <ul className={styles.paywallBenefits}>{benefits(plan, copy).map((benefit) => <li key={benefit}><Check aria-hidden="true" />{benefit}</li>)}</ul>
              <button className={styles.primary} disabled={busyRef.current || !target} onClick={() => void startCheckout(plan)}>
                {submitting === plan.plan_code ? copy.opening : interpolate(copy.choose, { plan: name, price: formattedPrice })}
              </button>
            </section>
          })}</div>}
    {(destinationError || errorCopy) && <p role="alert" className={styles.error}>{destinationError ? copy.invalidDestination : `${errorCopy?.title}${errorCopy?.body ? ` — ${errorCopy.body}` : ''}`}</p>}
    <div className={styles.paywallFooter}>
      <p><ShieldCheck aria-hidden="true" />{copy.reassurance}</p>
      <button type="button" className={styles.textButton} onClick={onClose}>{copy.continue}</button>
    </div>
  </DetailFrame>
}
