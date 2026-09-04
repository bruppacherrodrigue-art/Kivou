import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Check, CreditCard, Info } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { billing } from '../../api/endpoints'
import { describeError } from '../../api/errorCopy'
import type { CataloguePlan, Currency, PlanCatalogue, PurchasablePlan } from '../../api/types'
import { secureBillingDestination } from '../../billing/destination'
import { planFromSearch } from '../../billing/planRoute'
import { withRenderableSpaces } from '../../i18n'
import { fr } from '../../i18n/fr'
import { ReferenceLink } from '../router/ReferenceLink'
import { AuthShell } from './AuthShell'
import { Button } from './ui/button'

const PLAN_NAMES = {
  discovery: 'Découverte',
  essential: 'Essentiel',
  pro: 'Pro',
  scale: 'Scale',
} as const

function priceFor(plan: CataloguePlan, currency: Currency): string | null {
  const price = plan.monthly_price[currency]
  if (!price) return null
  return withRenderableSpaces(new Intl.NumberFormat('fr-CH', {
    style: 'currency',
    currency: price.currency.toUpperCase(),
    minimumFractionDigits: price.amount_minor_units % 100 === 0 ? 0 : 2,
  }).format(price.amount_minor_units / 100))
}

function cadenceLabel(value: CataloguePlan['entitlements']['alert_cadence']): string {
  const labels = {
    none: 'Aucune',
    weekly: 'Hebdomadaires',
    daily: 'Quotidiennes',
    priority: 'Prioritaires',
  } as const
  return labels[value]
}

function historyLabel(plan: CataloguePlan): string {
  const days = plan.entitlements.history_days
  if (days === null) return 'Tout l’historique disponible'
  if (days === 0) return 'Aucun historique antérieur'
  return `${days} jours`
}

function territoryLabel(plan: CataloguePlan): string {
  const limit = plan.entitlements.max_territories_per_icp
  if (limit !== null) return String(limit)
  const labels = { single: '1', multiple: 'Multiples', expanded: 'Étendus' } as const
  return labels[plan.entitlements.territory_mode]
}

export function CheckoutHandoff() {
  const location = useLocation()
  const planCode = planFromSearch(location.search)
  const [catalogue, setCatalogue] = useState<PlanCatalogue | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [checkoutError, setCheckoutError] = useState<unknown>(null)
  const [destinationError, setDestinationError] = useState(false)
  const [currency, setCurrency] = useState<Currency | null>(null)
  const [catalogueAttempt, setCatalogueAttempt] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const busyRef = useRef(false)
  const mountedRef = useRef(false)
  const submitGenerationRef = useRef(0)
  const activeSubmitRef = useRef<number | null>(null)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      submitGenerationRef.current += 1
    }
  }, [])

  useEffect(() => {
    submitGenerationRef.current += 1
    setCheckoutError(null)
    setDestinationError(false)
  }, [location.search])

  const submitIsCurrent = (generation: number) =>
    mountedRef.current && submitGenerationRef.current === generation

  useEffect(() => {
    let active = true
    setCatalogue(null)
    setLoadError(null)
    billing.plans().then(
      (next) => {
        if (active) setCatalogue(next)
      },
      (error) => {
        if (active) setLoadError(error)
      },
    )
    return () => {
      active = false
    }
  }, [catalogueAttempt])

  const plan = catalogue?.plans.find((item) => item.plan_code === planCode) ?? null
  const availableCurrencies = useMemo(
    () =>
      catalogue && plan
        ? catalogue.currencies.filter((candidate) => plan.monthly_price[candidate] !== undefined)
        : [],
    [catalogue, plan],
  )
  const selectedCurrency =
    currency && availableCurrencies.includes(currency)
      ? currency
      : availableCurrencies.includes('chf')
        ? 'chf'
        : (availableCurrencies[0] ?? null)

  async function submit() {
    if (busyRef.current || !plan || !selectedCurrency || !plan.purchasable) return
    if (!plan.monthly_price[selectedCurrency]) return

    busyRef.current = true
    const generation = ++submitGenerationRef.current
    activeSubmitRef.current = generation
    setSubmitting(true)
    setCheckoutError(null)
    setDestinationError(false)
    try {
      const session = await billing.checkout({
        plan: plan.plan_code as PurchasablePlan,
        currency: selectedCurrency,
      })
      if (!submitIsCurrent(generation)) return
      const destination = secureBillingDestination(session.checkout_url)
      if (!destination) {
        setDestinationError(true)
        return
      }
      window.location.assign(destination)
    } catch (error) {
      if (submitIsCurrent(generation)) setCheckoutError(error)
    } finally {
      if (activeSubmitRef.current === generation) {
        activeSubmitRef.current = null
        busyRef.current = false
        if (mountedRef.current) setSubmitting(false)
      }
    }
  }

  if (!catalogue && !loadError) {
    return (
      <AuthShell eyebrow="Passage à l’offre" title="Chargement de l’offre" description="Kivou vérifie le catalogue de facturation actuel avant toute action." wide>
        <div className="prototype-notice" role="status"><Info aria-hidden="true" /><p>Chargement du catalogue autoritaire…</p></div>
      </AuthShell>
    )
  }

  if (loadError) {
    const copy = describeError(loadError, fr)
    return (
      <AuthShell eyebrow="Passage à l’offre" title="Offre momentanément indisponible" description="Aucun paiement n’a été ouvert." wide>
        <p className="form-error" role="alert">{copy.title} {copy.body}</p>
        <div className="checkout-actions"><Button type="button" variant="outline" aria-label="Réessayer le chargement du catalogue" onClick={() => setCatalogueAttempt((current) => current + 1)}>Réessayer</Button><ReferenceLink className="text-link" href="/tarifs"><ArrowLeft aria-hidden="true" /> Comparer les offres</ReferenceLink></div>
      </AuthShell>
    )
  }

  if (!plan) {
    return (
      <AuthShell eyebrow="Passage à l’offre" title="Offre indisponible" description="Cette offre n’apparaît pas dans le catalogue de facturation actuel." wide>
        <p className="form-error" role="alert">Aucun paiement n’a été ouvert. Choisissez une offre actuellement proposée.</p>
        <div className="checkout-actions"><ReferenceLink className="text-link" href="/tarifs"><ArrowLeft aria-hidden="true" /> Comparer les offres</ReferenceLink></div>
      </AuthShell>
    )
  }

  if (plan.plan_code === 'discovery') {
    const signalCount = plan.entitlements.granted_signals
    const profileCount = plan.entitlements.max_active_icps
    const profileNoun = profileCount === 1 ? 'profil' : 'profils'
    const signalNoun = signalCount === 1 ? 'signal' : 'signaux'
    const signalAgreement = signalCount === 1 ? 'accordé' : 'accordés'
    return (
      <AuthShell eyebrow="Offre Découverte" title="Aucun paiement nécessaire" description="L’accès Découverte est défini par les droits renvoyés par le catalogue Kivou." wide>
        <div className="prototype-notice" role="note"><Info aria-hidden="true" /><p>Aucune session Stripe n’est créée pour cette offre.</p></div>
        <div className="checkout-summary-card"><span><Check aria-hidden="true" /></span><div><strong>Découverte · aucun paiement</strong><p>{profileCount} {profileNoun} · {signalCount} {signalNoun} {signalAgreement} · historique {historyLabel(plan).toLocaleLowerCase('fr')}</p></div></div>
        <div className="checkout-actions"><Button asChild className="primary-action"><ReferenceLink href="/app/signals">Voir {signalCount} {signalNoun} <ArrowRight aria-hidden="true" /></ReferenceLink></Button><ReferenceLink className="text-link" href="/tarifs"><ArrowLeft aria-hidden="true" /> Comparer les offres</ReferenceLink></div>
      </AuthShell>
    )
  }

  if (!plan.purchasable || availableCurrencies.length === 0 || !selectedCurrency) {
    return (
      <AuthShell eyebrow="Passage à l’offre" title={`Offre ${PLAN_NAMES[plan.plan_code]} indisponible`} description="Le catalogue actuel ne permet pas d’ouvrir un paiement pour cette offre." wide>
        <p className="form-error" role="alert">Cette offre est indisponible à l’achat dans les devises actuellement proposées. Aucun paiement n’a été ouvert.</p>
        <div className="checkout-actions"><ReferenceLink className="text-link" href="/tarifs"><ArrowLeft aria-hidden="true" /> Changer d’offre</ReferenceLink></div>
      </AuthShell>
    )
  }

  const price = priceFor(plan, selectedCurrency)
  const checkoutCopy = checkoutError ? describeError(checkoutError, fr) : null

  return (
    <AuthShell eyebrow="Passage à l’offre" title={`Finaliser l’offre ${PLAN_NAMES[plan.plan_code]}`} description="Kivou remettra le paiement à Stripe Checkout. Aucune donnée bancaire ne sera saisie sur cette interface." wide navigationDisabled={submitting}>
      <div className="prototype-notice" role="note"><Info aria-hidden="true" /><p>Le prix et les droits ci-dessous proviennent du catalogue Kivou actuellement chargé.</p></div>
      <section className="checkout-summary-card">
        <span><CreditCard aria-hidden="true" /></span>
        <div><p className="card-kicker">Récapitulatif</p><strong>{PLAN_NAMES[plan.plan_code]} · {price} / mois</strong><p>Facturation mensuelle et renouvellement automatique selon les conditions affichées avant paiement.</p></div>
      </section>
      <div className="form-field">
        <label htmlFor="checkout-currency">Devise</label>
        <select id="checkout-currency" className="lifecycle-select" value={selectedCurrency} disabled={submitting} onChange={(event) => setCurrency(event.target.value as Currency)}>
          {availableCurrencies.map((candidate) => <option key={candidate} value={candidate}>{candidate.toUpperCase()}</option>)}
        </select>
      </div>
      <dl className="checkout-entitlements"><div><dt>Profils</dt><dd>{plan.entitlements.max_active_icps}</dd></div><div><dt>Territoires</dt><dd>{territoryLabel(plan)}</dd></div><div><dt>Alertes</dt><dd>{cadenceLabel(plan.entitlements.alert_cadence)}</dd></div><div><dt>Historique</dt><dd>{historyLabel(plan)}</dd></div></dl>
      {destinationError
        ? <p className="form-error" role="alert">La destination de paiement reçue est invalide. Aucun paiement n’a été ouvert.</p>
        : checkoutCopy
          ? <p className="form-error" role="alert">{checkoutCopy.title} {checkoutCopy.body}</p>
          : null}
      <div className="checkout-actions"><Button type="button" disabled={submitting} className="primary-action" onClick={() => void submit()}>Continuer vers Stripe</Button><ReferenceLink className="text-link" href="/tarifs" aria-disabled={submitting || undefined} onClick={(event) => { if (busyRef.current) event.preventDefault() }}><ArrowLeft aria-hidden="true" /> Changer d’offre</ReferenceLink></div>
    </AuthShell>
  )
}
