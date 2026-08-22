import type { LocalisedText } from './publicDemoSignal'

export type HeroSignalCategory = 'materials' | 'workforce' | 'equipment' | 'service'

export interface LandingHeroSignal {
  readonly id: string
  readonly companyName: string
  readonly category: HeroSignalCategory
  readonly headline: LocalisedText
  readonly amountAndLocation: LocalisedText
  readonly summary: LocalisedText
  readonly opportunity: LocalisedText
  readonly timing: LocalisedText
  readonly strength: LocalisedText
  readonly timingBadge: LocalisedText
  readonly country: LocalisedText
  readonly detailUrl: '/exemple-de-signal' | '/signup'
  readonly sourceSystem: 'TED' | 'simap.ch'
  readonly sourceNotice: string
  readonly sourceUrl: string
  readonly publishedAt: string
  readonly awardDate: string
}

/* Projection publique et versionnée de quatre signaux du corpus de référence.
 *
 * Origine interne : tests/fixtures/signal100/signal100_blind.json.
 * Chaque entrée ci-dessous conserve l'identifiant du corpus et l'URL de la
 * publication officielle. Seuls les faits nécessaires au hero sont projetés ;
 * aucune donnée de compte, de score interne ou d'Acquisition Engine n'est
 * envoyée au navigateur.
 *
 * Les résumés traduisent les descriptifs publiés. Les « occasions
 * commerciales » restent des angles plausibles : elles ne sont jamais
 * présentées comme des commandes futures.
 */
export const landingHeroSignals: readonly LandingHeroSignal[] = [
  {
    id: 'ffd0dfe063ba123f0fdfc74f1afa06fb2fd5b41dea405425230cd5e350e47353',
    companyName: 'H. Hüther GmbH',
    category: 'materials',
    headline: {
      fr: 'H. Hüther GmbH remporte un chantier de 5,22 M€ à Munich',
      en: 'H. Hüther GmbH wins a €5.22m interior joinery contract in Munich',
    },
    amountAndLocation: {
      fr: '5,22 M€ · Munich, Allemagne',
      en: '€5.22m · Munich, Germany',
    },
    summary: {
      fr: 'Plus de 700 portes et huisseries, 5,5 km de plinthes et plusieurs équipements d’agencement figurent dans le périmètre publié.',
      en: 'More than 700 doors and frames, 5.5 km of skirting boards and several fit-out items appear in the published scope.',
    },
    opportunity: {
      fr: 'Portes, huisseries, produits bois et composants d’agencement compatibles',
      en: 'Compatible doors, frames, timber products and fit-out components',
    },
    timing: {
      fr: 'Attribution le 14 août 2026 · début d’exécution prévu le 28 octobre 2026.',
      en: 'Awarded on 14 August 2026 · expected execution start on 28 October 2026.',
    },
    strength: { fr: 'Angle commercial plausible', en: 'Plausible sales angle' },
    timingBadge: { fr: 'Calendrier publié', en: 'Published schedule' },
    country: { fr: 'Allemagne', en: 'Germany' },
    detailUrl: '/exemple-de-signal',
    sourceSystem: 'TED',
    sourceNotice: '568562-2026',
    sourceUrl: 'https://ted.europa.eu/en/notice/568562-2026/xml',
    publishedAt: '2026-08-17',
    awardDate: '2026-08-14',
  },
  {
    id: '389dafd9e46956b7fc65205eff4ea0572dc82fd99410c36d74b188ce4a9910fd',
    companyName: 'PKE Electronics AG',
    category: 'workforce',
    headline: {
      fr: 'PKE Electronics AG remporte un marché de vidéosurveillance de 2,24 M CHF en Suisse',
      en: 'PKE Electronics AG wins a CHF 2.24m video security contract in Switzerland',
    },
    amountAndLocation: {
      fr: '2,24 M CHF · Flumenthal, Suisse',
      en: 'CHF 2.24m · Flumenthal, Switzerland',
    },
    summary: {
      fr: 'Le marché couvre la fourniture, l’installation, la configuration et la mise en service des systèmes vidéo et d’interphonie.',
      en: 'The contract covers the supply, installation, configuration and commissioning of video and intercom systems.',
    },
    opportunity: {
      fr: 'Renforts d’installation et compétences de mise en service',
      en: 'Installation capacity and commissioning expertise',
    },
    timing: {
      fr: 'Attribution publiée le 11 août 2026 ; le périmètre couvre installation et mise en service.',
      en: 'Award published on 11 August 2026; the scope covers installation and commissioning.',
    },
    strength: { fr: 'Angle commercial plausible', en: 'Plausible sales angle' },
    timingBadge: { fr: 'Date publiée', en: 'Published date' },
    country: { fr: 'Suisse', en: 'Switzerland' },
    detailUrl: '/signup',
    sourceSystem: 'simap.ch',
    sourceNotice: 'dc12501a-6abc-4a2b-a692-1502bf6bba87',
    sourceUrl:
      'https://www.simap.ch/api/publications/v1/project/6c4cbd91-f20a-4c7c-9bc9-d7d2ec9c0933/publication-details/dc12501a-6abc-4a2b-a692-1502bf6bba87',
    publishedAt: '2026-08-12',
    awardDate: '2026-08-11',
  },
  {
    id: '2587f7ae40fcfc6736abd517a4211952f107a90adf58342edf62e556212f83af',
    companyName: 'Heinrich Würfel Metallbau GmbH',
    category: 'equipment',
    headline: {
      fr: 'Heinrich Würfel Metallbau GmbH remporte une rénovation de façade de 5,25 M€ à Aalen',
      en: 'Heinrich Würfel Metallbau GmbH wins a €5.25m façade renovation in Aalen',
    },
    amountAndLocation: {
      fr: '5,25 M€ · Aalen, Allemagne',
      en: '€5.25m · Aalen, Germany',
    },
    summary: {
      fr: 'Le descriptif mentionne 265 éléments de façade, 180 protections solaires et 1,6 km de pièces d’appui.',
      en: 'The published scope lists 265 façade elements, 180 solar protection systems and 1.6 km of sill components.',
    },
    opportunity: {
      fr: 'Composants métalliques, protections solaires et équipements de chantier',
      en: 'Metal components, solar protection and site equipment',
    },
    timing: {
      fr: 'Calendrier publié : exécution prévue du 8 février 2027 au 11 mai 2029.',
      en: 'Published schedule: expected execution from 8 February 2027 to 11 May 2029.',
    },
    strength: { fr: 'Angle commercial plausible', en: 'Plausible sales angle' },
    timingBadge: { fr: 'Calendrier publié', en: 'Published schedule' },
    country: { fr: 'Allemagne', en: 'Germany' },
    detailUrl: '/signup',
    sourceSystem: 'TED',
    sourceNotice: '569006-2026',
    sourceUrl: 'https://ted.europa.eu/en/notice/569006-2026/xml',
    publishedAt: '2026-08-17',
    awardDate: '2026-08-14',
  },
  {
    id: 'cb8cbc85dbfa8157581e187bc8c61b12b1c54d60dbbfe986a8b6dd9cfbe1e4b4',
    companyName: 'CRAM',
    category: 'service',
    headline: {
      fr: 'CRAM remporte un contrat de maintenance de 13,14 M€ en Normandie',
      en: 'CRAM wins a €13.14m maintenance contract in Normandy',
    },
    amountAndLocation: {
      fr: '13,14 M€ · Normandie, France',
      en: '€13.14m · Normandy, France',
    },
    summary: {
      fr: 'L’exploitation-maintenance inclut la gestion centralisée de l’énergie, des postes électriques et des capteurs de CO₂.',
      en: 'The operations and maintenance scope includes centralised energy management, electrical substations and CO₂ sensors.',
    },
    opportunity: {
      fr: 'Capacité de maintenance, systèmes énergétiques et renforts techniques',
      en: 'Maintenance capacity, energy systems and specialist support',
    },
    timing: {
      fr: 'Début d’exécution publié au 1er octobre 2026 · durée annoncée de douze ans.',
      en: 'Published execution start: 1 October 2026 · stated duration: twelve years.',
    },
    strength: { fr: 'Angle commercial plausible', en: 'Plausible sales angle' },
    timingBadge: { fr: 'Service récurrent', en: 'Recurring service' },
    country: { fr: 'France', en: 'France' },
    detailUrl: '/signup',
    sourceSystem: 'TED',
    sourceNotice: '569287-2026',
    sourceUrl: 'https://ted.europa.eu/en/notice/569287-2026/xml',
    publishedAt: '2026-08-17',
    awardDate: '2026-07-07',
  },
] as const
