import { useEffect, useState, type ReactNode } from 'react'
import { billing } from '../../api/endpoints'
import type {
  AlertCadence,
  CataloguePlan,
  Currency,
  PlanCatalogue,
  PlanCode,
} from '../../api/types'
import { ReferenceLink } from '../router/ReferenceLink'

export type PricingState =
  | { status: 'loading'; catalogue: null; currency: null }
  | { status: 'error'; catalogue: null; currency: null }
  | { status: 'ready'; catalogue: PlanCatalogue; currency: Currency | null }

export const PUBLIC_PLAN_CODES = ['discovery', 'essential', 'pro', 'scale'] as const

export function usePricingResource(): PricingState {
  const [state, setState] = useState<PricingState>({
    status: 'loading',
    catalogue: null,
    currency: null,
  })

  useEffect(() => {
    let active = true
    billing.plans().then((catalogue) => {
      if (!active) return
      const currency = catalogue.currencies.includes('chf')
        ? 'chf'
        : catalogue.currencies[0] ?? null
      setState({ status: 'ready', catalogue, currency })
    }).catch(() => {
      if (active) setState({ status: 'error', catalogue: null, currency: null })
    })
    return () => { active = false }
  }, [])

  return state
}

export interface PublicPrice {
  currency: string
  amount: string
}

export function publicPrice(
  plan: CataloguePlan,
  currency: Currency | null,
): PublicPrice | null {
  if (!currency) return null
  const price = plan.monthly_price[currency]
  if (!price) return null
  return {
    currency: price.currency.toUpperCase(),
    amount: new Intl.NumberFormat('fr-CH', {
      minimumFractionDigits: price.amount_minor_units % 100 === 0 ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(price.amount_minor_units / 100),
  }
}

export function publicPlans(catalogue: PlanCatalogue): CataloguePlan[] {
  const byCode = new Map(catalogue.plans.map((plan) => [plan.plan_code, plan]))
  return PUBLIC_PLAN_CODES.flatMap((code) => {
    const plan = byCode.get(code)
    return plan ? [plan] : []
  })
}

export function publicPlan(
  state: PricingState,
  planCode: PlanCode,
): CataloguePlan | null {
  if (state.status !== 'ready') return null
  return state.catalogue.plans.find((plan) => plan.plan_code === planCode) ?? null
}

export function publicPlanHref(plan: CataloguePlan): string {
  return plan.plan_code === 'discovery'
    ? '/signup?plan=discovery'
    : plan.purchasable
      ? `/signup?plan=${plan.plan_code}`
      : '/contact'
}

export function PublicPlanLink({
  state,
  planCode,
  className,
  ariaDescribedBy,
  children,
}: {
  state: PricingState
  planCode: PlanCode
  className: string
  ariaDescribedBy?: string
  children: ReactNode
}) {
  const plan = publicPlan(state, planCode)
  if (!plan) {
    return <span className={className} aria-disabled="true" aria-describedby={ariaDescribedBy}>{children}</span>
  }
  return <ReferenceLink className={className} href={publicPlanHref(plan)}>{children}</ReferenceLink>
}

export const PUBLIC_PLAN_NAMES: Record<PlanCode, string> = {
  discovery: 'Découverte',
  essential: 'Essentiel',
  pro: 'Pro',
  scale: 'Scale',
}

export const PUBLIC_PLAN_WHO: Record<PlanCode, string> = {
  discovery: 'Pour juger Kivou sur votre propre marché.',
  essential: 'Pour suivre un marché précis sans veille manuelle.',
  pro: 'Pour couvrir plusieurs segments et agir plus tôt.',
  scale: 'Pour prospecter sur une couverture européenne.',
}

export const PUBLIC_PLAN_CTA: Record<PlanCode, string> = {
  discovery: 'Commencer gratuitement',
  essential: 'Choisir Essentiel',
  pro: 'Choisir Pro',
  scale: 'Choisir Scale',
}

export function alertCadenceLabel(cadence: AlertCadence): string {
  if (cadence === 'weekly') return 'Alertes hebdomadaires'
  if (cadence === 'daily') return 'Alertes quotidiennes'
  if (cadence === 'priority') return 'Alertes prioritaires'
  return 'Sans alerte récurrente'
}

export function alertCadenceCompact(cadence: AlertCadence): string {
  if (cadence === 'weekly') return 'alertes hebdomadaires'
  if (cadence === 'daily') return 'alertes quotidiennes'
  if (cadence === 'priority') return 'alertes prioritaires'
  return 'sans alerte récurrente'
}

export function territoryLabel(plan: CataloguePlan): string {
  const limit = plan.entitlements.max_territories_per_icp
  if (limit !== null) return `${limit} ${limit === 1 ? 'territoire' : 'territoires'}`
  if (plan.entitlements.territory_mode === 'expanded') {
    return 'Couverture territoriale étendue'
  }
  return 'Plusieurs territoires par profil'
}

export function historyLabel(plan: CataloguePlan): string {
  const { history_days: days, history_scope: scope } = plan.entitlements
  if (scope === 'all_available') return 'Tout l’historique conservé'
  if (days && days > 0) return `${days} jours d’historique`
  return 'Signaux reçus'
}

export function profileLabel(plan: CataloguePlan): string {
  const count = plan.entitlements.max_active_icps
  return `${count} ${count === 1 ? 'profil cible' : 'profils cibles'}`
}

export function signalCountLabel(
  count: number,
  qualifier?: 'complet' | 'gratuit',
): string {
  const noun = count === 1 ? 'signal' : 'signaux'
  const adjective = qualifier ? ` ${qualifier}${count === 1 ? '' : 's'}` : ''
  return `${count} ${noun}${adjective}`
}

export function discoveryCompact(plan: CataloguePlan): string {
  const count = plan.entitlements.granted_signals
  return `${signalCountLabel(count, 'complet')}, ${alertCadenceCompact(plan.entitlements.alert_cadence)}`
}

export function frenchCardinal(value: number): string {
  const words = [
    'zéro', 'un', 'deux', 'trois', 'quatre', 'cinq', 'six', 'sept', 'huit', 'neuf',
    'dix', 'onze', 'douze', 'treize', 'quatorze', 'quinze', 'seize', 'dix-sept',
    'dix-huit', 'dix-neuf', 'vingt',
  ]
  return words[value] ?? new Intl.NumberFormat('fr-CH').format(value)
}
