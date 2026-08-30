import type { CataloguePlan } from '../api/types'
import { PublicPageMeta } from '../components/PublicPageMeta'
import {
  PUBLIC_PLAN_NAMES,
  PublicPlanLink,
  PublicPricingRetry,
  type PricingState,
  alertCadenceCompact,
  discoveryCompact,
  profileLabel,
  publicPlan,
  publicPrice,
  signalCountLabel,
  territoryLabel,
  usePricingResource,
} from '../reference/public/PricingResource'
import { ReferenceLink } from '../reference/router/ReferenceLink'

export function Landing() {
  const pricing = usePricingResource()
  const discovery = publicPlan(pricing, 'discovery')
  const discoveryStatusId = discovery ? undefined : 'landing-discovery-status'
  const plansByCode = new Map(
    pricing.status === 'ready'
      ? pricing.catalogue.plans.map((plan) => [plan.plan_code, plan])
      : [],
  )

  return (
    <>
      <PublicPageMeta
        title="Kivou | Signaux commerciaux post-attribution"
        description="Kivou transforme les marchés publics attribués en signaux commerciaux documentés."
        canonicalPath="/"
      />
      <main id="main">
        <section className="home-hero">
          <div className="container hero-grid">
            <div className="hero-copy">
              <p className="eyebrow">Veille commerciale post-attribution</p>
              <h1>Repérez les entreprises qui viennent de gagner un marché public.</h1>
              <p className="lead">Kivou rassemble le marché remporté, les volumes publiés, les dates utiles et les besoins d’exécution à vérifier avant de contacter le gagnant.</p>
              <div className="button-row">
                <PublicPlanLink state={pricing} planCode="discovery" className="btn primary" ariaDescribedBy={discoveryStatusId}>{landingDiscoveryCta(discovery)}</PublicPlanLink>
                <ReferenceLink className="btn secondary" href="/exemple-de-signal">Examiner un signal complet</ReferenceLink>
              </div>
              <p
                className="hero-facts"
                id={discoveryStatusId}
                role={discovery ? undefined : pricing.status === 'error' ? 'alert' : 'status'}
              >
                {discovery
                  ? <>{signalCountLabel(discovery.entitlements.granted_signals, 'gratuit')} · Sans carte bancaire · {capitalize(alertCadenceCompact(discovery.entitlements.alert_cadence))}</>
                  : landingDiscoveryStateText(pricing)}
                <PublicPricingRetry state={pricing} />
              </p>
            </div>
            <article className="glass signal-card hero-signal" aria-labelledby="home-signal-title">
              <div className="signal-card-top"><div><span className="micro-label">Signal récent</span><strong id="home-signal-title">H. Hüther GmbH</strong></div><span className="verified">Vérifié</span></div>
              <div className="signal-value"><small>Marché attribué</small><strong>5,22 M€</strong></div>
              <p className="signal-title">Plus de 700 portes et huisseries, 5,5 km de plinthes et des travaux d’agencement à Munich.</p>
              <dl className="signal-meta"><div><dt>Début prévu</dt><dd>28 octobre 2026</dd></div><div><dt>Source</dt><dd>TED 568562-2026</dd></div></dl>
              <ReferenceLink className="card-link" href="/exemple-de-signal">Consulter le signal complet</ReferenceLink>
            </article>
          </div>
        </section>

        <section className="proof-strip" aria-label="Contenu d’un signal">
          <div className="container proof-line"><strong>Dans chaque signal</strong><span>l’entreprise gagnante, le marché, un besoin d’exécution à vérifier, le calendrier et la source.</span></div>
        </section>

        <section className="section dashboard-demo" aria-labelledby="dashboard-title">
          <div className="container">
            <div className="dashboard-intro">
              <header className="section-head">
                <p className="eyebrow">Le dashboard Kivou</p>
                <h2 id="dashboard-title">Voici ce que vous voyez lorsqu’un signal remonte.</h2>
                <p className="lead">Le gagnant, le marché, les volumes, le calendrier, les questions à vérifier et la source sont réunis dans la même vue.</p>
              </header>
              <ReferenceLink className="text-link" href="/exemple-de-signal">Voir l’exemple complet</ReferenceLink>
            </div>

            <div className="glass dashboard-preview signal-path-preview" aria-label="Chemin de lecture d’un signal Kivou">
              <div className="signal-path-step"><span>01</span><div><strong>Fait publié</strong><p>L’attribution, le titulaire, le périmètre et la source officielle.</p></div></div>
              <div className="signal-path-step"><span>02</span><div><strong>Pertinence expliquée</strong><p>La correspondance avec votre offre, votre territoire et votre ciblage.</p></div></div>
              <div className="signal-path-step"><span>03</span><div><strong>Inconnues visibles</strong><p>Ce que l’avis ne permet pas d’affirmer et qu’il reste à vérifier.</p></div></div>
              <div className="signal-path-step"><span>04</span><div><strong>Votre apprentissage</strong><p>Une note personnelle, ajoutée après les faits, sans modifier la source.</p></div></div>
            </div>
          </div>
        </section>

        <section className="section">
          <div className="container">
            <header className="section-head">
              <p className="eyebrow">Avant de prospecter</p>
              <h2>Les questions auxquelles un signal doit répondre.</h2>
            </header>
            <div className="benefit-grid">
              <article><span>Entreprise</span><h3>Qui a gagné ?</h3><p>Le nom du titulaire et les informations publiques utiles pour l’identifier.</p></article>
              <article><span>Marché</span><h3>Que doit-elle exécuter ?</h3><p>L’objet, le montant, la localisation et les volumes disponibles.</p></article>
              <article><span>Analyse</span><h3>Où votre offre peut-elle être utile ?</h3><p>Les besoins possibles sont distingués des faits publiés et restent à confirmer.</p></article>
              <article><span>Calendrier</span><h3>Quand examiner le compte ?</h3><p>Les dates de publication et d’exécution donnent le contexte du moment.</p></article>
            </div>
          </div>
        </section>

        <section className="dark-section">
          <div className="container summary-grid">
            <div><p className="eyebrow">Comment ça marche</p><h2>Vous définissez la cible. Kivou suit les attributions.</h2></div>
            <ol className="summary-steps">
              <li><span>01</span><div><b>Décrivez votre offre</b><p>Produits, entreprises cibles et territoires.</p></div></li>
              <li><span>02</span><div><b>Kivou relève les faits utiles</b><p>Gagnant, marché, volumes et calendrier.</p></div></li>
              <li><span>03</span><div><b>Vous gardez votre lecture</b><p>Approfondir le compte, l’écarter ou consigner une note.</p></div></li>
            </ol>
            <ReferenceLink className="btn mint-btn" href="/produit">Voir la méthode</ReferenceLink>
          </div>
        </section>

        <section className="section">
          <div className="container offers-overview">
            <div className="offers-copy">
              <p className="eyebrow">Les offres</p>
              <h2>Commencez gratuitement, puis élargissez votre couverture si nécessaire.</h2>
              <p className="lead">Le contenu d’un signal reste identique. Les plans payants augmentent le nombre de profils, les pays couverts, la fréquence des alertes et l’historique.</p>
              <div className="button-row"><PublicPlanLink state={pricing} planCode="discovery" className="btn primary" ariaDescribedBy={discoveryStatusId}>Commencer gratuitement</PublicPlanLink><ReferenceLink className="btn secondary" href="/tarifs">Comparer les offres</ReferenceLink></div>
            </div>
            <div className="glass offer-matrix" aria-label="Aperçu des offres Kivou">
              {(['discovery', 'essential', 'pro', 'scale'] as const).map((code) => {
                const plan = plansByCode.get(code)
                const price = plan ? publicPrice(plan, pricing.currency) : null
                const unavailable = landingOfferUnavailable(pricing)
                return (
                  <div key={code}>
                    <span><strong>{PUBLIC_PLAN_NAMES[code]}</strong><small>{plan ? plan.plan_code === 'discovery' ? discoveryCompact(plan) : `${profileLabel(plan)} · ${territoryLabel(plan)}` : unavailable.detail}</small></span>
                    <b>{plan ? plan.plan_code === 'discovery' ? 'Gratuit' : price ? `${price.currency} ${price.amount}` : 'Indisponible' : unavailable.price}</b>
                  </div>
                )
              })}
              <p>{pricing.status === 'ready' ? 'Tous les prix affichés sont mensuels.' : pricing.status === 'loading' ? 'Chargement des tarifs…' : 'Les tarifs ne peuvent pas être affichés.'}</p>
            </div>
          </div>
        </section>
      </main>
    </>
  )
}

function capitalize(value: string): string {
  return `${value.charAt(0).toUpperCase()}${value.slice(1)}`
}

function landingDiscoveryCta(plan: CataloguePlan | null): string {
  const count = plan?.entitlements.granted_signals
  if (count === 1) return 'Voir mon premier signal'
  if (count && count > 1) return `Voir mes ${count} premiers signaux`
  return 'Voir mes premiers signaux'
}

function landingDiscoveryStateText(state: PricingState): string {
  if (state.status === 'loading') return 'Chargement des offres…'
  if (state.status === 'error') return 'Les offres sont momentanément indisponibles.'
  return 'L’offre Découverte est absente du catalogue.'
}

function landingOfferUnavailable(state: PricingState): { detail: string; price: string } {
  if (state.status === 'loading') return { detail: 'Chargement de l’offre…', price: '…' }
  if (state.status === 'error') {
    return { detail: 'Données momentanément indisponibles', price: 'Indisponible' }
  }
  return { detail: 'Offre absente du catalogue', price: 'Non proposée' }
}
