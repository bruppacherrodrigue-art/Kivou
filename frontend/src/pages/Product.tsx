import type { AlertCadence, CataloguePlan } from '../api/types'
import { PublicPageMeta } from '../components/PublicPageMeta'
import {
  PublicPlanLink,
  frenchCardinal,
  publicPlan,
  usePricingResource,
} from '../reference/public/PricingResource'
import { ReferenceLink } from '../reference/router/ReferenceLink'

export function Product() {
  const pricing = usePricingResource()
  const discovery = publicPlan(pricing, 'discovery')

  return (
    <>
      <PublicPageMeta
        title="Comment ça marche | Kivou"
        description="La méthode Kivou, du ciblage à l’analyse d’un marché public attribué."
        canonicalPath="/produit"
      />
      <main id="main">
        <section className="page-hero">
          <div className="container hero-grid">
            <div className="hero-copy">
              <p className="eyebrow">Comment ça marche</p>
              <h1>Kivou suit ce qui se passe après l’attribution.</h1>
              <p className="lead">Vous décrivez ce que vous vendez. Kivou relève les marchés attribués qui correspondent, identifie le gagnant et rassemble les faits utiles pour décider si ce compte mérite une approche.</p>
              <div className="button-row"><PublicPlanLink state={pricing} planCode="discovery" className="btn primary">Configurer mon profil</PublicPlanLink><ReferenceLink className="btn secondary" href="/exemple-de-signal">Voir le résultat</ReferenceLink></div>
            </div>
            <div className="glass pipeline-card">
              <p className="pipeline-label">Le parcours d’un signal</p>
              <ol className="pipeline">
                <li className="pipeline-item"><span className="pipeline-number">01</span><div><b>Votre profil</b><span>Offre, entreprises cibles et territoires.</span></div></li>
                <li className="pipeline-item"><span className="pipeline-number">02</span><div><b>Une attribution</b><span>Un gagnant et un marché correspondant à votre couverture.</span></div></li>
                <li className="pipeline-item"><span className="pipeline-number">03</span><div><b>L’analyse</b><span>Faits publiés, besoin possible et calendrier.</span></div></li>
                <li className="pipeline-item"><span className="pipeline-number">04</span><div><b>Votre lecture</b><span>Approfondir, écarter ou consigner une note.</span></div></li>
              </ol>
            </div>
          </div>
        </section>

        <section className="dark-section">
          <div className="container dark-grid">
            <div>
              <p className="eyebrow">Pourquoi après l’attribution</p>
              <h2>Le gagnant doit maintenant exécuter le marché.</h2>
              <p className="lead">Le contrat peut l’amener à mobiliser des personnes, des équipements, des matériaux, des partenaires ou des expertises. Kivou cherche les faits qui permettent d’examiner ces besoins sans les présenter comme des achats certains.</p>
            </div>
            <dl className="post-award-facts">
              <div><dt>L’avis établit</dt><dd>le titulaire, l’objet, le montant, les lots et les dates disponibles.</dd></div>
              <div><dt>Kivou rapproche</dt><dd>ces faits de votre offre, de vos cibles et de vos territoires.</dd></div>
              <div><dt>Vous tranchez</dt><dd>si le compte vaut une recherche ou une prise de contact.</dd></div>
            </dl>
          </div>
        </section>

        <section className="section" id="fonctionnement">
          <div className="container method-layout">
            <header className="section-head">
              <p className="eyebrow">La méthode Kivou</p>
              <h2>Cinq étapes, du ciblage au signal.</h2>
              <p className="lead">Le ciblage vient de vous. Les faits viennent des sources publiques. L’analyse relie les deux et indique ce qui reste à confirmer.</p>
            </header>
            <ol className="method-list">
              <li><span>01</span><div><h3>Définissez votre ciblage</h3><p>Votre offre, les entreprises que vous pouvez aider et les territoires à couvrir.</p></div></li>
              <li><span>02</span><div><h3>Les attributions sont surveillées</h3><p>Kivou suit les avis officiels correspondant à la couverture choisie.</p></div></li>
              <li><span>03</span><div><h3>Les faits sont structurés</h3><p>Gagnant, objet, montant, lieu, lots, volumes et dates lorsqu’ils sont publiés.</p></div></li>
              <li><span>04</span><div><h3>La correspondance est expliquée</h3><p>Le besoin possible est rapproché de votre activité, avec les limites de l’analyse.</p></div></li>
              <li><span>05</span><div><h3>Le signal arrive dans votre veille</h3><p>Vous disposez du contexte et de la source pour choisir la suite.</p></div></li>
            </ol>
          </div>
        </section>

        <section className="section compact">
          <div className="container">
            <header className="section-head">
              <p className="eyebrow">Un cas concret</p>
              <h2>Des faits publiés à l’angle commercial à vérifier.</h2>
              <p className="lead">Voici comment Kivou lit l’attribution remportée par H. Hüther GmbH à Munich.</p>
            </header>
            <div className="glass fact-module">
              <div className="fact-side published"><p className="panel-label">Faits publiés</p><h3>Un marché de 5,22 M€</h3><ul className="clean-list"><li>Plus de 700 portes et huisseries</li><li>5,5 km de plinthes</li><li>Travaux à Munich</li><li>Début prévu le 28 octobre 2026</li></ul></div>
              <div className="analysis-bridge"><span>Kivou analyse</span></div>
              <div className="fact-side analysis"><p className="panel-label">À examiner</p><h3>Des besoins possibles autour de l’agencement</h3><ul className="clean-list"><li>Produits bois et composants compatibles</li><li>Vitrage et éléments d’agencement</li><li>Calendrier commercial relié aux dates publiées</li><li>Source TED disponible pour contrôle</li></ul></div>
            </div>
            <div className="center-link"><ReferenceLink className="btn secondary" href="/exemple-de-signal">Lire l’analyse complète</ReferenceLink></div>
          </div>
        </section>

        <section className="section">
          <div className="container">
            <header className="section-head">
              <p className="eyebrow">Calendrier et source</p>
              <h2>Le signal montre quand les faits ont été publiés et d’où ils viennent.</h2>
            </header>
            <div className="assurance-grid">
              <article className="glass assurance-card">
                <p className="panel-label">Dates du cas Hüther</p>
                <dl className="compact-timeline"><div><dt>14 août 2026</dt><dd>Attribution et signature</dd></div><div><dt>17 août 2026</dt><dd>Publication de l’avis</dd></div><div><dt>28 octobre 2026</dt><dd>Début d’exécution prévu</dd></div></dl>
              </article>
              <article className="glass assurance-card analysis">
                <p className="panel-label">Source associée</p>
                <h3>TED 568562-2026</h3>
                <p>L’avis officiel permet de contrôler le gagnant, le montant, l’objet et les dates. L’analyse commerciale apparaît séparément afin de ne pas confondre un fait publié avec un besoin possible.</p>
                <ReferenceLink className="text-link" href="/exemple-de-signal">Voir les champs vérifiés</ReferenceLink>
              </article>
            </div>
          </div>
        </section>

        <div className="container">
          <section className="final-cta">
            <div className="final-cta-grid"><div><h2>Jugez Kivou sur des signaux complets.</h2><p role={pricing.status === 'loading' ? 'status' : pricing.status === 'error' ? 'alert' : undefined}>{discovery ? productDiscoverySentence(discovery) : pricing.status === 'loading' ? 'Chargement de l’offre Découverte…' : pricing.status === 'error' ? 'Les tarifs sont momentanément indisponibles.' : 'L’offre Découverte est absente du catalogue.'}</p></div><div className="button-row"><PublicPlanLink state={pricing} planCode="discovery" className="btn primary">Voir mes premiers signaux</PublicPlanLink><ReferenceLink className="btn secondary" href="/tarifs">Voir les tarifs</ReferenceLink></div></div>
          </section>
        </div>
      </main>
    </>
  )
}

function productDiscoverySentence(plan: CataloguePlan): string {
  const count = plan.entitlements.granted_signals
  const access = count === 1
    ? 'Le premier est accessible gratuitement'
    : `Les ${frenchCardinal(count)} premiers sont accessibles gratuitement`
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
