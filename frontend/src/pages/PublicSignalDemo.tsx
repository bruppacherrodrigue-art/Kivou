import type { AlertCadence, CataloguePlan } from '../api/types'
import { PublicPageMeta } from '../components/PublicPageMeta'
import {
  PublicPlanLink,
  PublicPricingRetry,
  frenchCardinal,
  publicPlan,
  usePricingResource,
} from '../reference/public/PricingResource'
import { ReferenceLink } from '../reference/router/ReferenceLink'

const ted = 'https://ted.europa.eu/en/notice/568562-2026/xml'

export function PublicSignalDemo() {
  const pricing = usePricingResource()
  const discovery = publicPlan(pricing, 'discovery')

  return (
    <>
      <PublicPageMeta
        title="Exemple de signal | Kivou"
        description="Un signal Kivou construit à partir d’un avis d’attribution réel."
        canonicalPath="/exemple-de-signal"
      />
      <main id="main" tabIndex={-1}>
        <section className="page-hero">
          <div className="container hero-grid">
            <div className="hero-copy">
              <p className="eyebrow">Exemple de signal</p>
              <h1>H. Hüther GmbH a remporté un marché de 5,22 M€ à Munich.</h1>
              <p className="lead">L’avis publié donne les volumes, le calendrier d’exécution et l’entreprise gagnante. Kivou utilise ces faits pour faire ressortir les sujets commerciaux qui méritent une vérification.</p>
              <p className="signal-origin">Source TED 568562-2026 · Vérifié le 20 août 2026</p>
              <div className="button-row"><a className="btn primary" href="#analyse">Lire l’analyse Kivou</a><a className="btn secondary" href={ted} target="_blank" rel="noreferrer" aria-label="Ouvrir l’avis officiel TED dans un nouvel onglet">Ouvrir l’avis TED</a></div>
            </div>
            <article className="glass signal-card" aria-labelledby="signal-company">
              <div className="signal-card-top"><strong id="signal-company">H. Hüther GmbH</strong><span className="verified">Source vérifiée</span></div>
              <div className="signal-value"><small>Montant attribué</small><strong>5,22 M€</strong></div>
              <h2 className="signal-title">Menuiseries intérieures, portes et mobilier</h2>
              <p className="original-title">Intitulé publié : Tischlerarbeiten Innentueren und Moebel</p>
              <dl className="signal-meta"><div><dt>Lieu</dt><dd>Munich, Allemagne</dd></div><div><dt>Début prévu</dt><dd>28 octobre 2026</dd></div><div><dt>Acheteur</dt><dd>Staatl. Bauamt München 1</dd></div><div><dt>Référence</dt><dd>26-000.723.722</dd></div></dl>
            </article>
          </div>
        </section>

        <section className="section">
          <div className="container">
            <header className="section-head"><p className="eyebrow">Les faits publiés</p><h2>Ce que l’avis TED indique.</h2><p className="lead">L’analyse commence par les éléments établis dans la source officielle.</p></header>
            <div className="data-grid">
              <article className="glass data-card"><h3>Le marché en bref</h3><dl className="key-data"><div><dt>Gagnant</dt><dd>H. Hüther GmbH</dd></div><div><dt>Acheteur</dt><dd>Staatl. Bauamt München 1</dd></div><div><dt>Montant exact</dt><dd>5 219 043,35 EUR</dd></div><div><dt>Référence</dt><dd>26-000.723.722</dd></div><div><dt>CPV</dt><dd>45420000</dd></div><div><dt>Lieu</dt><dd>80335 München</dd></div><div><dt>Attribution et signature</dt><dd>14 août 2026</dd></div><div><dt>Publication</dt><dd>17 août 2026</dd></div><div><dt>Exécution</dt><dd>du 28 octobre 2026 au 29 octobre 2027</dd></div></dl></article>
              <article className="glass data-card"><h3>Volumes publiés</h3><div className="volume-grid"><div className="volume"><strong>497</strong><span>huisseries et portes bois</span></div><div className="volume"><strong>234</strong><span>huisseries acier et portes bois</span></div><div className="volume"><strong>5 485 m</strong><span>de plinthes</span></div><div className="volume"><strong>425 m²</strong><span>de revêtement mural bois</span></div><div className="volume"><strong>24</strong><span>éléments vitrés</span></div><div className="volume"><strong>13</strong><span>kitchenettes</span></div></div><p className="source-note">Ces quantités viennent du descriptif de l’avis d’attribution. Elles ne remplacent pas un cahier des charges.</p></article>
            </div>
          </div>
        </section>

        <section className="section compact" id="analyse">
          <div className="container">
            <header className="section-head"><p className="eyebrow">L’analyse Kivou</p><h2>Quatre sujets commerciaux à vérifier.</h2><p className="lead">L’avis décrit des travaux d’agencement. Il ne dit pas quels fournisseurs sont déjà engagés ni quels achats restent ouverts.</p></header>
            <div className="glass opportunity-panel">
              <p className="panel-label">Besoins possibles</p>
              <div className="opportunity-rows">
                <article><h3>Portes et huisseries</h3><p>Les volumes publiés peuvent concerner des fabricants, distributeurs ou spécialistes de composants compatibles.</p></article>
                <article><h3>Plinthes et produits bois</h3><p>La longueur annoncée et les surfaces de revêtement donnent un périmètre concret à qualifier.</p></article>
                <article><h3>Vitrage</h3><p>Les éléments vitrés peuvent rendre pertinents certains produits ou services spécialisés.</p></article>
                <article><h3>Kitchenettes et agencement</h3><p>Les équipements mentionnés peuvent ouvrir un sujet auprès de fournisseurs adaptés.</p></article>
              </div>
            </div>
          </div>
        </section>

        <section className="section">
          <div className="container">
            <header className="section-head"><p className="eyebrow">Le calendrier</p><h2>Les dates situent le moment commercial.</h2><p className="lead">Elles permettent de replacer le gagnant dans sa phase de préparation ou d’exécution.</p></header>
            <div className="timeline"><div className="timeline-item"><span className="timeline-dot">14.08</span><b>Attribution et signature</b><span>14 août 2026</span></div><div className="timeline-item"><span className="timeline-dot">17.08</span><b>Publication</b><span>17 août 2026</span></div><div className="timeline-item"><span className="timeline-dot">28.10</span><b>Début prévu</b><span>28 octobre 2026</span></div><div className="timeline-item"><span className="timeline-dot">2027</span><b>Fin prévue</b><span>29 octobre 2027</span></div></div>
            <ol className="action-list"><li>Comparer les volumes à votre offre.</li><li>Consulter l’avis et les éléments publiés.</li><li>Identifier le rôle achats, approvisionnement ou opérations pertinent.</li><li>Décider si le contact vaut la peine.</li></ol>
          </div>
        </section>

        <section className="section compact">
          <div className="container">
            <header className="section-head"><p className="eyebrow">Correspondance avec votre profil</p><h2>La pertinence dépend de votre activité.</h2><p className="lead">Kivou compare le signal à l’offre, au territoire et aux cibles que vous avez définis.</p></header>
            <div className="glass fit-panel"><ul className="fit-list"><li><strong>Votre offre</strong><span>couvre des produits compatibles.</span></li><li><strong>Votre territoire</strong><span>inclut la zone de Munich.</span></li><li><strong>Votre cible</strong><span>comprend cette catégorie d’entreprise.</span></li><li><strong>Votre priorité</strong><span>correspond à la taille du marché.</span></li><li><strong>Votre cycle</strong><span>reste compatible avec le calendrier.</span></li></ul></div>
          </div>
        </section>

        <section className="section compact">
          <div className="container">
            <header className="section-head"><p className="eyebrow">Votre apprentissage</p><h2>La note vient après les faits.</h2><p className="lead">Après avoir lu le marché, la source et les inconnues, vous pouvez conserver ce que vous en retenez sans modifier les données publiées.</p></header>
            <article className="glass assurance-card analysis"><p className="panel-label">Exemple de note</p><h3>Point à approfondir</h3><p>Vérifier si les portes et huisseries restent à sourcer avant le démarrage prévu, puis identifier la fonction responsable des achats du chantier.</p><p className="source-note">Cette note appartient à l’utilisateur. Elle n’est ni un fait TED, ni une analyse présentée comme certaine.</p></article>
          </div>
        </section>

        <section className="section">
          <div className="container">
            <header className="section-head"><p className="eyebrow">Les sources</p><h2>L’entreprise et l’avis restent accessibles.</h2><p className="lead">Les éléments publics d’identification de l’entreprise et les données du marché sont présentés séparément pour garder leur origine claire.</p></header>
            <div className="evidence-grid">
              <article className="glass evidence-card"><h3>Entreprise identifiée</h3><div className="company-lines"><strong>H. Hüther GmbH</strong><span>Graseweg 8<br />34346 Hedemünden<br />Allemagne</span><a href="https://huether-gmbh.de" target="_blank" rel="noreferrer" aria-label="Ouvrir le site de H. Hüther GmbH dans un nouvel onglet">huether-gmbh.de</a><a href="tel:+49554596060">+49 5545 9606-0</a><span>Identifiant publié : DE115302781</span></div><p className="source-note">Coordonnées issues du site public de l’entreprise, vérifiées le 22 août 2026. Elles ne proviennent pas de l’avis TED.</p></article>
              <article className="glass evidence-card"><h3>Traçabilité du marché</h3><ul className="trace-list"><li><span>Avis officiel</span><b><a className="text-link" href={ted} target="_blank" rel="noreferrer" aria-label="Ouvrir l’avis TED dans un nouvel onglet">TED 568562-2026</a></b></li><li><span>Montant</span><b>5 219 043,35 EUR</b></li><li><span>CPV</span><b>45420000</b></li><li><span>Lot</span><b>LOT-0000</b></li><li><span>Référence</span><b>26-000.723.722</b></li><li><span>Signature</span><b>14 août 2026</b></li></ul><details className="technical"><summary>Origine des données</summary><p>Le CPV, le montant et le lot disposent ici d’une provenance technique détaillée. Les autres faits sont contrôlés dans l’avis officiel.</p></details></article>
            </div>
            <p className="caveat"><strong>Limite de l’analyse :</strong> Kivou n’a pas accès au cahier des charges. Cet exemple repose sur l’avis TED et son descriptif ; il indique un besoin possible, pas un achat annoncé.</p>
          </div>
        </section>

        <div className="container"><section className="final-cta"><div className="final-cta-grid"><div><h2>Recevez les signaux qui correspondent à votre activité.</h2><p role={pricing.status === 'loading' ? 'status' : pricing.status === 'error' ? 'alert' : undefined}>{discovery ? signalDiscoverySentence(discovery) : pricing.status === 'loading' ? 'Chargement de l’offre Découverte…' : pricing.status === 'error' ? 'Les tarifs sont momentanément indisponibles.' : 'L’offre Découverte est absente du catalogue.'}<PublicPricingRetry state={pricing} /></p></div><div className="button-row"><PublicPlanLink state={pricing} planCode="discovery" className="btn primary">Commencer gratuitement</PublicPlanLink><ReferenceLink className="btn secondary" href="/tarifs">Voir les tarifs</ReferenceLink></div></div></section></div>
      </main>
    </>
  )
}

function signalDiscoverySentence(plan: CataloguePlan): string {
  const count = plan.entitlements.granted_signals
  const access = count === 1
    ? 'Le premier est accessible dès l’inscription'
    : `Les ${frenchCardinal(count)} premiers sont accessibles dès l’inscription`
  if (plan.entitlements.alert_cadence === 'none') {
    return `${access}, sans alerte récurrente.`
  }
  return `${access}. ${cadenceSentence(plan.entitlements.alert_cadence)}`
}

function cadenceSentence(cadence: Exclude<AlertCadence, 'none'>): string {
  if (cadence === 'weekly') return 'Les alertes sont hebdomadaires.'
  if (cadence === 'daily') return 'Les alertes sont quotidiennes.'
  return 'Les alertes sont prioritaires.'
}
