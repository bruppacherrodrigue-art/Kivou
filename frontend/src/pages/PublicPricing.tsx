import type { AlertCadence, CataloguePlan, Currency, PlanCode } from '../api/types'
import { PublicPageMeta } from '../components/PublicPageMeta'
import {
  PUBLIC_PLAN_CODES,
  PUBLIC_PLAN_CTA,
  PUBLIC_PLAN_NAMES,
  PUBLIC_PLAN_WHO,
  PublicPlanLink,
  PublicPricingRetry,
  type PricingState,
  alertCadenceCompact,
  alertCadenceLabel,
  discoveryCompact,
  frenchCardinal,
  historyLabel,
  profileLabel,
  publicPlan,
  publicPlanHref,
  publicPlans,
  publicPrice,
  signalCountLabel,
  territoryLabel,
  usePricingResource,
} from '../reference/public/PricingResource'
import { ReferenceLink } from '../reference/router/ReferenceLink'

export function PublicPricing() {
  const pricing = usePricingResource()
  const discovery = publicPlan(pricing, 'discovery')
  const plans = pricing.status === 'ready' ? publicPlans(pricing.catalogue) : []
  const plansByCode = new Map(plans.map((plan) => [plan.plan_code, plan]))

  return (
    <>
      <PublicPageMeta
        title="Tarifs | Kivou"
        description="Les quatre offres mensuelles Kivou, de Découverte à Scale."
        canonicalPath="/tarifs"
      />
      <main id="main" className="pricing-page" tabIndex={-1}>
        <header className="pricing-hero container">
          <p className="eyebrow">Tarifs mensuels</p>
          <h1>Choisissez la couverture adaptée à votre prospection.</h1>
          <p className="lead">Chaque offre donne accès au même contenu dans un signal. Le nombre de profils, la géographie, la fréquence et l’historique évoluent avec le plan.</p>
          <p
            className="hero-facts"
            role={pricing.status === 'loading' ? 'status' : pricing.status === 'error' ? 'alert' : undefined}
          >
            {pricingHeroFacts(pricing, discovery)}
            <PublicPricingRetry state={pricing} />
          </p>
        </header>

        <section className="container pricing-grid" aria-label="Offres Kivou" aria-busy={pricing.status === 'loading'}>
          {PUBLIC_PLAN_CODES.map((code) => {
            const plan = plansByCode.get(code)
            return plan
              ? <PricingCard key={code} plan={plan} currency={pricing.currency} plansByCode={plansByCode} />
              : <UnavailablePricingCard key={code} code={code} state={pricing} />
          })}
        </section>

        <section className="section compact">
          <div className="container">
            <header className="section-head"><p className="eyebrow">Comparaison</p><h2>Ce qui change d’une offre à l’autre.</h2></header>
            <div className="table-wrap">
              <table>
                <caption>Comparaison des offres Kivou</caption>
                <thead><tr><th scope="col">Couverture</th>{PUBLIC_PLAN_CODES.map((code) => <th scope="col" className={plansByCode.get(code)?.recommended ? 'pro-col' : undefined} key={code}>{PUBLIC_PLAN_NAMES[code]}</th>)}</tr></thead>
                <tbody>
                  <ComparisonRow label="Prix mensuel" plans={plans} currency={pricing.status === 'ready' ? pricing.currency : null} value={(plan, currency) => plan.plan_code === 'discovery' ? 'Gratuit' : priceText(plan, currency)} />
                  <ComparisonRow label="Accès au flux" plans={plans} value={(plan) => plan.entitlements.feed_access ? 'Inclus' : 'Non inclus'} />
                  <ComparisonRow label="Signaux complets" plans={plans} value={(plan) => plan.plan_code === 'discovery' ? discoveryCompact(plan) : plan.entitlements.feed_access ? `Tous ceux ${plan.entitlements.max_active_icps === 1 ? 'du profil' : 'des profils'}` : 'Non inclus'} />
                  <ComparisonRow label="Profils cibles" plans={plans} value={profileLabel} />
                  <ComparisonRow label="Géographie" plans={plans} value={territoryLabel} />
                  <ComparisonRow label="Alertes" plans={plans} value={(plan) => alertCadenceLabel(plan.entitlements.alert_cadence)} />
                  <ComparisonRow label="Historique" plans={plans} value={historyLabel} />
                </tbody>
              </table>
            </div>
            <p className="pricing-terms">Prix mensuels, TVA en sus. Les conditions d’abonnement figurent dans les <ReferenceLink href="/informations-legales#cgu">Conditions générales</ReferenceLink>.</p>
          </div>
        </section>

        <div className="container"><section className="final-cta"><div className="final-cta-grid"><div><h2>{pricingFinalCopy(pricing, discovery).heading}</h2><p id={discovery ? undefined : 'pricing-discovery-status'}>{pricingFinalCopy(pricing, discovery).body}</p></div><div className="button-row"><PublicPlanLink state={pricing} planCode="discovery" className="btn primary" ariaDescribedBy={discovery ? undefined : 'pricing-discovery-status'}>Commencer gratuitement</PublicPlanLink><ReferenceLink className="btn secondary" href="/exemple-de-signal">Voir un signal</ReferenceLink></div></div></section></div>
      </main>
    </>
  )
}

function PricingCard({
  plan,
  currency,
  plansByCode,
}: {
  plan: CataloguePlan
  currency: Currency | null
  plansByCode: ReadonlyMap<PlanCode, CataloguePlan>
}) {
  const price = publicPrice(plan, currency)
  const free = plan.plan_code === 'discovery'
  const checkoutPriceUnavailable = !free && plan.purchasable && !price
  const classes = `glass price-card${plan.recommended ? ' recommended' : ''}`

  return (
    <article className={classes}>
      {plan.recommended ? <div className="price-band">Recommandé</div> : null}
      <h2 className="plan-name">{PUBLIC_PLAN_NAMES[plan.plan_code]}</h2>
      <p className="plan-who">{PUBLIC_PLAN_WHO[plan.plan_code]}</p>
      <p className={`plan-price${free ? ' free' : ''}`}>
        {free ? <strong>Gratuit</strong> : price ? <><small>{price.currency}</small><strong>{price.amount}</strong><span>/mois</span></> : <strong>Indisponible</strong>}
      </p>
      <p className="plan-billing">{free ? 'Accès gratuit' : price ? 'par mois' : 'Tarif indisponible'}</p>
      <hr />
      <p className="plan-intro">Inclus</p>
      <PricingFeatureList plan={plan} plansByCode={plansByCode} />
      {checkoutPriceUnavailable
        ? <span className={`btn ${plan.recommended ? 'primary' : 'secondary'}`} aria-disabled="true">{PUBLIC_PLAN_CTA[plan.plan_code]}</span>
        : <ReferenceLink className={`btn ${plan.recommended ? 'primary' : 'secondary'}`} href={publicPlanHref(plan)}>{PUBLIC_PLAN_CTA[plan.plan_code]}</ReferenceLink>}
    </article>
  )
}

function UnavailablePricingCard({ code, state }: { code: PlanCode; state: PricingState }) {
  const copy = unavailableCardCopy(state)
  return (
    <article className="glass price-card" aria-busy={state.status === 'loading'}>
      <h2 className="plan-name">{PUBLIC_PLAN_NAMES[code]}</h2>
      <p className="plan-who">{PUBLIC_PLAN_WHO[code]}</p>
      <p className="plan-price"><strong>{copy.price}</strong></p>
      <p className="plan-billing">{copy.billing}</p>
      <hr />
      <p className="plan-intro">Informations</p>
      <ul aria-label={copy.featuresLabel}>{copy.features.map((feature) => <li key={feature}>{feature}</li>)}</ul>
      <span className="btn secondary" aria-disabled="true">{PUBLIC_PLAN_CTA[code]}</span>
    </article>
  )
}

function ComparisonRow({
  label,
  plans,
  currency = null,
  value,
}: {
  label: string
  plans: CataloguePlan[]
  currency?: Currency | null
  value: (plan: CataloguePlan, currency: Currency | null) => string
}) {
  const byCode = new Map(plans.map((plan) => [plan.plan_code, plan]))
  return (
    <tr>
      <th scope="row">{label}</th>
      {PUBLIC_PLAN_CODES.map((code) => {
        const plan = byCode.get(code)
        return <td className={plan?.recommended ? 'pro-col' : undefined} key={code}>{plan ? value(plan, currency) : '—'}</td>
      })}
    </tr>
  )
}

function priceText(plan: CataloguePlan, currency: Currency | null): string {
  const price = publicPrice(plan, currency)
  return price ? `${price.currency} ${price.amount}` : 'Indisponible'
}

function capitalize(value: string): string {
  return `${value.charAt(0).toUpperCase()}${value.slice(1)}`
}

function unavailableCardCopy(state: PricingState): {
  price: string
  billing: string
  features: string[]
  featuresLabel: string
} {
  if (state.status === 'loading') {
    return {
      price: 'Chargement…',
      billing: 'Catalogue en cours de chargement',
      features: [
        'Chargement du contenu de l’offre…',
        'Chargement de la couverture…',
        'Chargement des accès…',
        'Chargement des alertes…',
        'Chargement de l’historique…',
      ],
      featuresLabel: 'Informations de l’offre en cours de chargement',
    }
  }
  if (state.status === 'error') {
    return {
      price: 'Indisponible',
      billing: 'Catalogue indisponible',
      features: [
        'Contenu indisponible',
        'Couverture indisponible',
        'Accès indisponibles',
        'Alertes indisponibles',
        'Historique indisponible',
      ],
      featuresLabel: 'Informations de l’offre momentanément indisponibles',
    }
  }
  return {
    price: 'Indisponible',
    billing: 'Offre absente du catalogue',
    features: [
      'Contenu non publié',
      'Couverture non publiée',
      'Accès non publiés',
      'Alertes non publiées',
      'Historique non publié',
    ],
    featuresLabel: 'Offre absente du catalogue',
  }
}

function PricingFeatureList({
  plan,
  plansByCode,
}: {
  plan: CataloguePlan
  plansByCode: ReadonlyMap<PlanCode, CataloguePlan>
}) {
  const e = plan.entitlements

  if (plan.plan_code === 'discovery') {
    return (
      <ul>
        <li>{signalCountLabel(e.granted_signals, 'complet')} dès l’inscription</li>
        <li>{cardCadenceLabel(e.alert_cadence)}</li>
        <li>{profileLabel(plan)} · {territoryLabel(plan)}</li>
        <li>{e.detail_access ? 'Entreprise, marché, besoin possible et calendrier' : 'Détail des signaux non inclus'}</li>
        <li>{e.evidence_access ? 'Source officielle associée' : 'Source officielle non incluse'}</li>
      </ul>
    )
  }

  if (plan.plan_code === 'essential') {
    return (
      <ul>
        <li>{e.feed_access ? 'Tous les signaux correspondant à votre cible' : 'Accès au flux non inclus'}</li>
        <li>{profileLabel(plan)} · {territoryLabel(plan)}</li>
        <li>{contextAndSourceLabel(plan)}</li>
        <li>{cardCadenceLabel(e.alert_cadence)}</li>
        <li>{cardHistoryLabel(plan, true)}</li>
      </ul>
    )
  }

  if (plan.plan_code === 'pro') {
    const essential = plansByCode.get('essential')
    return (
      <ul>
        <li>{essential && includesPlan(plan, essential) ? 'Tout Essentiel' : accessSummary(plan)}</li>
        <li>{profileLabel(plan)} · {territoryLabel(plan)}</li>
        <li>{cardCadenceLabel(e.alert_cadence)}</li>
        <li>{cardHistoryLabel(plan, false)}</li>
        <li>{contextAndSourceLabel(plan)}</li>
      </ul>
    )
  }

  const pro = plansByCode.get('pro')
  return (
    <ul>
      <li>{pro && includesPlan(plan, pro) ? 'Tout Pro' : accessSummary(plan)}</li>
      <li>{profileLabel(plan)}</li>
      <li>{territoryLabel(plan)}</li>
      <li>{cardCadenceLabel(e.alert_cadence)}</li>
      <li>{cardHistoryLabel(plan, false)}</li>
    </ul>
  )
}

function cardCadenceLabel(cadence: AlertCadence): string {
  if (cadence === 'weekly') return 'Alerte hebdomadaire'
  if (cadence === 'daily') return 'Alertes quotidiennes'
  if (cadence === 'priority') return 'Alertes prioritaires après détection'
  return 'Sans alerte récurrente'
}

function cardHistoryLabel(plan: CataloguePlan, atActivation: boolean): string {
  const { history_days: days, history_scope: scope } = plan.entitlements
  if (scope === 'all_available') return historyLabel(plan)
  if (days && days > 0) return `${days} jours d’historique${atActivation ? ' à l’activation' : ''}`
  return 'Signaux reçus'
}

function contextAndSourceLabel(plan: CataloguePlan): string {
  const { detail_access: detail, evidence_access: evidence } = plan.entitlements
  if (detail && evidence) return 'Contexte, calendrier et source'
  if (detail) return 'Contexte et calendrier, sans source associée'
  if (evidence) return 'Source officielle, sans contexte détaillé'
  return 'Contexte détaillé et source non inclus'
}

function accessSummary(plan: CataloguePlan): string {
  const { feed_access: feed, detail_access: detail, evidence_access: evidence } = plan.entitlements
  return [
    feed ? 'flux inclus' : 'flux non inclus',
    detail ? 'contexte inclus' : 'contexte non inclus',
    evidence ? 'source incluse' : 'source non incluse',
  ].join(' · ')
}

const TERRITORY_RANK = { single: 0, multiple: 1, expanded: 2 } as const
const CADENCE_RANK = { none: 0, weekly: 1, daily: 2, priority: 3 } as const
const FILTER_RANK = { minimum: 0, basic: 1, advanced: 2 } as const
const EXPORT_RANK = { none: 0, manual: 1, scheduled: 2 } as const

function includesPlan(candidate: CataloguePlan, baseline: CataloguePlan): boolean {
  const c = candidate.entitlements
  const b = baseline.entitlements
  return c.max_active_icps >= b.max_active_icps
    && includesHistory(candidate, baseline)
    && includesTerritories(candidate, baseline)
    && (!b.feed_access || c.feed_access)
    && (!b.detail_access || c.detail_access)
    && (!b.evidence_access || c.evidence_access)
    && CADENCE_RANK[c.alert_cadence] >= CADENCE_RANK[b.alert_cadence]
    && FILTER_RANK[c.filter_level] >= FILTER_RANK[b.filter_level]
    && EXPORT_RANK[c.export_level] >= EXPORT_RANK[b.export_level]
    && c.granted_signals >= b.granted_signals
}

function includesHistory(candidate: CataloguePlan, baseline: CataloguePlan): boolean {
  const c = candidate.entitlements
  const b = baseline.entitlements
  if (b.history_scope === 'all_available') return c.history_scope === 'all_available'
  if (c.history_scope === 'all_available') return true
  if (c.history_days === null || b.history_days === null) return false
  return c.history_days >= b.history_days
}

function includesTerritories(candidate: CataloguePlan, baseline: CataloguePlan): boolean {
  const c = candidate.entitlements
  const b = baseline.entitlements
  const candidateRank = TERRITORY_RANK[c.territory_mode]
  const baselineRank = TERRITORY_RANK[b.territory_mode]
  if (candidateRank < baselineRank) return false
  if (b.max_territories_per_icp === null) return c.max_territories_per_icp === null
  if (c.max_territories_per_icp !== null) {
    return c.max_territories_per_icp >= b.max_territories_per_icp
  }
  return candidateRank > baselineRank
}

function pricingHeroFacts(state: PricingState, discovery: CataloguePlan | null): string {
  if (discovery) {
    return `${signalCountLabel(discovery.entitlements.granted_signals, 'gratuit')} · Sans carte bancaire pour commencer · ${capitalize(alertCadenceCompact(discovery.entitlements.alert_cadence))}`
  }
  if (state.status === 'loading') return 'Chargement des offres…'
  if (state.status === 'error') return 'Les tarifs sont momentanément indisponibles.'
  return 'Offre Découverte absente du catalogue.'
}

function pricingFinalCopy(
  state: PricingState,
  discovery: CataloguePlan | null,
): { heading: string; body: string } {
  if (discovery) {
    const count = discovery.entitlements.granted_signals
    return {
      heading: count === 1
        ? 'Commencez avec un signal complet.'
        : `Commencez avec ${frenchCardinal(count)} signaux complets.`,
      body: pricingDiscoverySentence(discovery.entitlements.alert_cadence),
    }
  }
  if (state.status === 'loading') {
    return { heading: 'Découvrez les offres Kivou.', body: 'Chargement de l’offre Découverte…' }
  }
  if (state.status === 'error') {
    return {
      heading: 'Les offres sont momentanément indisponibles.',
      body: 'Le catalogue ne permet pas encore d’afficher l’offre Découverte.',
    }
  }
  return {
    heading: 'L’offre Découverte est absente du catalogue.',
    body: 'Aucun avantage ni tarif n’est affiché pour cette offre.',
  }
}

function pricingDiscoverySentence(cadence: AlertCadence): string {
  if (cadence === 'none') return 'Commencez sans carte bancaire, sans alerte récurrente.'
  if (cadence === 'weekly') return 'Commencez sans carte bancaire. Les alertes sont hebdomadaires.'
  if (cadence === 'daily') return 'Commencez sans carte bancaire. Les alertes sont quotidiennes.'
  return 'Commencez sans carte bancaire. Les alertes sont prioritaires.'
}
