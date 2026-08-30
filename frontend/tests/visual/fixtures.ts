import type { Page } from '@playwright/test'

import type {
  BillingStatus,
  CompanyProfile,
  FeedPage,
  LockedFeedItem,
  Me,
  NotificationPreference,
  PlanCatalogue,
  TargetIcp,
  UnlockedDetail,
  UnlockedFeedItem,
} from '../../src/api/types'

export type SignalFact = {
  label: string;
  value: string;
};

export type SignalScope = {
  value: string;
  label: string;
};

export type MatchReason = {
  label: string;
  value: string;
};

export type CompanyRecord = {
  id: string;
  name: string;
  initials: string;
  summary: string;
  location: string;
  facts: SignalFact[];
  identitySource: string;
  identityLimit: string;
  rolesToFind: string[];
};

export type AwardSignal = {
  id: string;
  company: CompanyRecord;
  title: string;
  shortTitle: string;
  amount: string;
  amountShort: string;
  contractDate: string;
  contractDateIso: string;
  publicationDate: string;
  execution: string;
  location: string;
  buyer: string;
  notice: string;
  cpv: string;
  sourceUrl: string;
  summary: string;
  scope: SignalScope[];
  matchReasons: MatchReason[];
  questionsToVerify: string[];
  limit: string;
  matchLabel: string;
};

const huether: CompanyRecord = {
  id: "h-huether",
  name: "H. Hüther GmbH",
  initials: "HH",
  summary: "Titulaire d’un marché de menuiserie intérieure à Munich.",
  location: "Hedemünden, Allemagne",
  facts: [
    { label: "Raison sociale", value: "H. Hüther GmbH" },
    { label: "Adresse", value: "Graseweg 8, 34346 Hedemünden" },
    { label: "Pays et région", value: "Allemagne · Basse-Saxe" },
  ],
  identitySource: "Avis TED pour le statut de titulaire · site public de l’entreprise pour l’adresse",
  identityLimit: "Aucun contact d’achat n’est confirmé dans les données présentées.",
  rolesToFind: ["Achats ou approvisionnement", "Conduite de travaux", "Direction de projet"],
};

const karlSchmitt: CompanyRecord = {
  id: "karl-schmitt",
  name: "Karl Schmitt GmbH",
  initials: "KS",
  summary: "Titulaire des travaux d’agencement du Krankenhaus Rummelsberg.",
  location: "Allemagne",
  facts: [
    { label: "Raison sociale publiée", value: "Karl Schmitt GmbH" },
    { label: "Pays", value: "Allemagne" },
    { label: "Marché associé", value: "Agencement hospitalier à Schwarzenbruck" },
  ],
  identitySource: "Fiche organisation de l’avis TED 588058-2026",
  identityLimit: "Le titulaire est identifié, mais aucun contact d’achat n’est validé dans cette maquette.",
  rolesToFind: ["Achats ou approvisionnement", "Conduite de travaux", "Direction de projet"],
};

const tmAusbau: CompanyRecord = {
  id: "tm-ausbau",
  name: "TM Ausbau GmbH",
  initials: "TM",
  summary: "Titulaire du lot de portes intérieures bois du Campus Ost à Munich.",
  location: "Munich, Allemagne",
  facts: [
    { label: "Raison sociale publiée", value: "TM Ausbau GmbH" },
    { label: "Localisation publiée", value: "Munich" },
    { label: "Pays", value: "Allemagne" },
  ],
  identitySource: "Fiche organisation de l’avis TED 584863-2026",
  identityLimit: "La date distincte de sélection du titulaire n’est pas publiée ; seule la conclusion du contrat l’est.",
  rolesToFind: ["Achats portes et quincaillerie", "Conduite de travaux", "Responsable du lot"],
};

const gsh: CompanyRecord = {
  id: "gsh",
  name: "GSH GmbH",
  initials: "GSH",
  summary: "Titulaire d’un marché de portes intérieures et habillages à Gunzenhausen.",
  location: "Allemagne",
  facts: [
    { label: "Raison sociale publiée", value: "GSH GmbH" },
    { label: "Pays", value: "Allemagne" },
    { label: "Marché associé", value: "Portes intérieures à Gunzenhausen" },
  ],
  identitySource: "Fiche organisation de l’avis TED 573430-2026",
  identityLimit: "La personne responsable des achats de ce chantier n’est pas publiée.",
  rolesToFind: ["Achats portes et composants", "Conduite de travaux", "Direction de projet"],
};

const sedlmeyr: CompanyRecord = {
  id: "sedlmeyr",
  name: "Sedlmeyr Spezialtüren GmbH",
  initials: "SS",
  summary: "Titulaire des portes, huisseries et vitrages du projet Zielstattstraße à Munich.",
  location: "Friedberg, Allemagne",
  facts: [
    { label: "Raison sociale publiée", value: "Sedlmeyr Spezialtüren GmbH" },
    { label: "Localisation publiée", value: "Friedberg" },
    { label: "Pays", value: "Allemagne" },
  ],
  identitySource: "Fiche organisation de l’avis TED 542161-2026",
  identityLimit: "La date distincte de sélection du titulaire n’est pas publiée ; seule la conclusion du contrat l’est.",
  rolesToFind: ["Achats portes et huisseries", "Conduite de travaux", "Responsable du marché"],
};

const garzon: CompanyRecord = {
  id: "garzon-butor",
  name: "Garzon Butor zrt.",
  initials: "GB",
  summary: "Titulaire du mobilier intégré du campus scolaire de Deisenhofen.",
  location: "Székesfehérvár, Hongrie",
  facts: [
    { label: "Raison sociale", value: "Garzon Butor zrt." },
    { label: "Adresse publiée", value: "Bakony u. 4, 8000 Székesfehérvár" },
    { label: "Taille publiée", value: "Entreprise moyenne · Hongrie" },
  ],
  identitySource: "Fiche organisation de l’avis TED 506746-2026",
  identityLimit: "La fiche identifie le titulaire, mais pas la personne responsable des achats pour ce chantier.",
  rolesToFind: ["Achats projet", "Direction de chantier", "Responsable du marché"],
};

export const awardSignals: AwardSignal[] = [
  {
    id: "h-huether-munich",
    company: huether,
    title: "H. Hüther GmbH, titulaire d’un marché de 5,22 M€ à Munich",
    shortTitle: "Menuiseries intérieures et mobilier à Munich",
    amount: "5 219 043,35 EUR",
    amountShort: "5,22 M€",
    contractDate: "14 août 2026",
    contractDateIso: "2026-08-14",
    publicationDate: "17 août 2026",
    execution: "28 oct. 2026 au 29 oct. 2027",
    location: "Munich, Allemagne",
    buyer: "Staatliches Bauamt München 1",
    notice: "568562-2026",
    cpv: "45420000",
    sourceUrl: "https://ted.europa.eu/en/notice/-/detail/568562-2026",
    summary: "L’avis identifie le titulaire, le calendrier et des volumes précis de portes, huisseries et agencement.",
    scope: [
      { value: "497", label: "portes et huisseries bois" },
      { value: "234", label: "huisseries acier et portes bois" },
      { value: "5 485 m", label: "plinthes" },
      { value: "425 m²", label: "revêtement mural bois" },
      { value: "24", label: "éléments vitrés" },
      { value: "13", label: "kitchenettes" },
    ],
    matchReasons: [
      { label: "Produits", value: "Portes, huisseries, composants bois et équipements d’agencement." },
      { label: "Territoire", value: "Le projet se situe à Munich, dans la zone suivie en Bavière." },
      { label: "Calendrier", value: "Le début d’exécution est prévu le 28 octobre 2026." },
    ],
    questionsToVerify: [
      "Les fournisseurs de portes et huisseries sont-ils déjà sélectionnés ?",
      "Quels lots seront réalisés directement par le titulaire ?",
      "Quels achats restent ouverts avant le démarrage du chantier ?",
    ],
    limit: "L’avis ne précise pas si des achats fournisseurs restent ouverts.",
    matchLabel: "Portes et agencement",
  },
  {
    id: "karl-schmitt-rummelsberg",
    company: karlSchmitt,
    title: "Karl Schmitt remporte les travaux d’agencement du Krankenhaus Rummelsberg",
    shortTitle: "Agencement hospitalier à Rummelsberg",
    amount: "396 116,00 EUR",
    amountShort: "396,1 k€",
    contractDate: "25 août 2026",
    contractDateIso: "2026-08-25",
    publicationDate: "26 août 2026",
    execution: "9 nov. 2026 au 2 avr. 2027",
    location: "Schwarzenbruck, Allemagne",
    buyer: "Krankenhaus Rummelsberg GmbH",
    notice: "588058-2026",
    cpv: "45421150 · 45421153",
    sourceUrl: "https://ted.europa.eu/de/notice/-/detail/588058-2026",
    summary: "L’avis attribue la fabrication et la pose de mobilier intégré, comptoirs, cuisines et autres éléments d’agencement hospitalier.",
    scope: [
      { value: "2", label: "ensembles de mobilier intégré" },
      { value: "5", label: "comptoirs" },
      { value: "3", label: "revêtements muraux" },
      { value: "19", label: "cuisines" },
      { value: "266", label: "appuis de fenêtre" },
    ],
    matchReasons: [
      { label: "Produits", value: "Mobilier intégré, comptoirs, cuisines et composants d’agencement." },
      { label: "Territoire", value: "Le projet se situe à Schwarzenbruck, en Bavière." },
      { label: "Calendrier", value: "L’exécution publiée doit commencer le 9 novembre 2026." },
    ],
    questionsToVerify: [
      "Quels composants seront fabriqués en interne ou achetés ?",
      "Les quincailleries et équipements des cuisines sont-ils déjà commandés ?",
      "Qui pilote les achats avant le démarrage de novembre ?",
    ],
    limit: "L’attribution prouve le contrat et son périmètre, pas l’existence d’un besoin fournisseur encore ouvert.",
    matchLabel: "Agencement hospitalier",
  },
  {
    id: "tm-ausbau-campus-ost",
    company: tmAusbau,
    title: "TM Ausbau remporte les portes intérieures bois du Campus Ost à Munich",
    shortTitle: "Portes intérieures bois du Campus Ost",
    amount: "428 157,00 EUR",
    amountShort: "428,2 k€",
    contractDate: "6 juillet 2026",
    contractDateIso: "2026-07-06",
    publicationDate: "25 août 2026",
    execution: "31 juil. 2026 au 17 mars 2027",
    location: "Munich, Allemagne",
    buyer: "Landeshauptstadt München · Baureferat",
    notice: "584863-2026",
    cpv: "45421131 · 44221200",
    sourceUrl: "https://ted.europa.eu/de/notice/-/detail/584863-2026",
    summary: "Le contrat porte sur plusieurs familles de portes bois, leurs huisseries et le raccordement de composants électriques.",
    scope: [
      { value: "110", label: "portes à âme pleine" },
      { value: "60", label: "portes à âme tubulaire" },
      { value: "20", label: "portes à cadre bois" },
      { value: "9", label: "portes spéciales bois" },
      { value: "Exigences", label: "feu, acoustique, humidité et chimie" },
    ],
    matchReasons: [
      { label: "Produits", value: "Portes bois, huisseries et composants techniques de portes." },
      { label: "Territoire", value: "Le Campus Ost se situe à Munich, au cœur de la zone suivie." },
      { label: "Calendrier", value: "L’exécution publiée court jusqu’en mars 2027." },
    ],
    questionsToVerify: [
      "Les huisseries et quincailleries sont-elles déjà entièrement sourcées ?",
      "Quels composants électriques de portes restent à approvisionner ?",
      "Quel responsable pilote le lot sur le Campus Ost ?",
    ],
    limit: "La date de sélection du titulaire n’est pas publiée séparément de la conclusion du contrat.",
    matchLabel: "Portes techniques",
  },
  {
    id: "gsh-gunzenhausen",
    company: gsh,
    title: "GSH remporte un marché de portes intérieures à Gunzenhausen",
    shortTitle: "Portes intérieures et habillages à Gunzenhausen",
    amount: "739 342,50 EUR",
    amountShort: "739,3 k€",
    contractDate: "18 août 2026",
    contractDateIso: "2026-08-18",
    publicationDate: "19 août 2026",
    execution: "27 juil. 2026 au 15 févr. 2027",
    location: "Gunzenhausen, Allemagne",
    buyer: "Staatliches Bauamt Ansbach",
    notice: "573430-2026",
    cpv: "45421131",
    sourceUrl: "https://ted.europa.eu/de/notice/-/detail/573430-2026",
    summary: "L’avis couvre des portes bois, des ensembles vitrés, des habillages et des équipements de signalétique incendie.",
    scope: [
      { value: "Portes", label: "bois, coupe-feu et pare-fumée" },
      { value: "Vitrages", label: "ensembles bois-verre" },
      { value: "Habillages", label: "tableaux, murs et plafonds" },
      { value: "Équipement", label: "butées et signalétique incendie" },
    ],
    matchReasons: [
      { label: "Produits", value: "Portes, vitrages, habillages bois et accessoires de pose." },
      { label: "Territoire", value: "Le chantier se situe à Gunzenhausen, en Bavière." },
      { label: "Calendrier", value: "La période publiée court jusqu’au 15 février 2027." },
    ],
    questionsToVerify: [
      "Quels modèles de portes et huisseries restent à commander ?",
      "Les accessoires coupe-feu et la signalétique sont-ils déjà attribués ?",
      "Pourquoi la date de début publiée précède-t-elle le contrat ?",
    ],
    limit: "La date de début publiée, le 27 juillet, précède la conclusion du contrat du 18 août ; Kivou conserve cette anomalie visible.",
    matchLabel: "Portes et habillages",
  },
  {
    id: "sedlmeyr-zielstattstrasse",
    company: sedlmeyr,
    title: "Sedlmeyr remporte 1,49 M€ de portes et huisseries à Munich",
    shortTitle: "Portes, huisseries et vitrages à Zielstattstraße",
    amount: "1 489 624,00 EUR",
    amountShort: "1,49 M€",
    contractDate: "31 juillet 2026",
    contractDateIso: "2026-07-31",
    publicationDate: "5 août 2026",
    execution: "10 août 2026 au 3 avr. 2028",
    location: "Munich, Allemagne",
    buyer: "Landeshauptstadt München · Baureferat",
    notice: "542161-2026",
    cpv: "45421131",
    sourceUrl: "https://ted.europa.eu/de/notice/-/detail/542161-2026",
    summary: "Le marché porte sur près de 500 portes intérieures, plusieurs types d’huisseries, des vitrages fixes et des fenêtres-caissons.",
    scope: [
      { value: "489", label: "portes intérieures environ" },
      { value: "25", label: "vitrages fixes" },
      { value: "2", label: "vitrages coupe-feu F90" },
      { value: "13", label: "fenêtres-caissons" },
      { value: "Finitions", label: "vernis, placage ou HPL" },
    ],
    matchReasons: [
      { label: "Produits", value: "Portes, huisseries bois, acier ou aluminium, vitrages et finitions HPL." },
      { label: "Territoire", value: "Le projet Zielstattstraße se situe à Munich." },
      { label: "Calendrier", value: "L’exécution publiée s’étend jusqu’en avril 2028." },
    ],
    questionsToVerify: [
      "Quelles huisseries et quincailleries sont encore à approvisionner ?",
      "Comment les livraisons sont-elles phasées jusqu’en 2028 ?",
      "Quel interlocuteur pilote les achats du projet munichois ?",
    ],
    limit: "Le volume et le calendrier sont publiés, mais les fournisseurs déjà retenus ne le sont pas.",
    matchLabel: "489 portes environ",
  },
  {
    id: "garzon-deisenhofen",
    company: garzon,
    title: "Garzon Butor remporte le mobilier intégré du campus de Deisenhofen",
    shortTitle: "Mobilier intégré du campus de Deisenhofen",
    amount: "812 831,46 EUR",
    amountShort: "812,8 k€",
    contractDate: "21 juillet 2026",
    contractDateIso: "2026-07-21",
    publicationDate: "22 juillet 2026",
    execution: "À partir du 7 août 2026 · durée publiée de 452 jours",
    location: "Oberhaching, Allemagne",
    buyer: "Zweckverband Staatliche weiterführende Schulen im Süden des Landkreises München",
    notice: "506746-2026",
    cpv: "45421153",
    sourceUrl: "https://ted.europa.eu/de/notice/-/detail/506746-2026",
    summary: "Le contrat porte sur les armoires, habillages, assises et cuisines intégrées des écoles du nouveau campus.",
    scope: [
      { value: "706 m", label: "armoires intégrées" },
      { value: "300 m", label: "surfaces acoustiques sur armoires" },
      { value: "350 m", label: "habillages au-dessus des armoires" },
      { value: "170 m", label: "surfaces acoustiques sur habillages" },
      { value: "4", label: "cuisines équipées" },
      { value: "Assises", label: "couloirs et salles des professeurs" },
    ],
    matchReasons: [
      { label: "Produits", value: "Mobilier intégré, façades acoustiques, assises et cuisines équipées." },
      { label: "Territoire", value: "Le campus est situé à Oberhaching, dans le Landkreis München." },
      { label: "Calendrier", value: "L’exécution publiée a démarré le 7 août 2026 pour 452 jours." },
    ],
    questionsToVerify: [
      "Quels composants sont fabriqués en interne ou achetés auprès de fournisseurs ?",
      "Les quincailleries et façades acoustiques sont-elles déjà commandées ?",
      "Quel responsable pilote l’exécution locale en Bavière ?",
    ],
    limit: "Le marché confirme le besoin et le titulaire, pas l’état actuel de ses commandes fournisseurs.",
    matchLabel: "Mobilier intégré",
  },
];

const REFERENCE_METADATA = {
  'h-huether-munich': {
    amount: '5219043.35',
    companyCountry: 'DE',
    placeCountry: 'DE',
    locality: 'Munich',
    magnitude: 'over_5m',
    publication: '2026-08-17',
  },
  'karl-schmitt-rummelsberg': {
    amount: '396116.00',
    companyCountry: 'DE',
    placeCountry: 'DE',
    locality: 'Schwarzenbruck',
    magnitude: '250k_1m',
    publication: '2026-08-26',
  },
  'tm-ausbau-campus-ost': {
    amount: '428157.00',
    companyCountry: 'DE',
    placeCountry: 'DE',
    locality: 'Munich',
    magnitude: '250k_1m',
    publication: '2026-08-25',
  },
  'gsh-gunzenhausen': {
    amount: '739342.50',
    companyCountry: 'DE',
    placeCountry: 'DE',
    locality: 'Gunzenhausen',
    magnitude: '250k_1m',
    publication: '2026-08-19',
  },
  'sedlmeyr-zielstattstrasse': {
    amount: '1489624.00',
    companyCountry: 'DE',
    placeCountry: 'DE',
    locality: 'Munich',
    magnitude: '1m_5m',
    publication: '2026-08-05',
  },
  'garzon-deisenhofen': {
    amount: '812831.46',
    companyCountry: 'HU',
    placeCountry: 'DE',
    locality: 'Oberhaching',
    magnitude: '250k_1m',
    publication: '2026-07-22',
  },
} as const satisfies Record<ReferenceSignalId, {
  amount: string
  companyCountry: string
  placeCountry: string
  locality: string
  magnitude: '250k_1m' | '1m_5m' | 'over_5m'
  publication: string
}>

type ReferenceSignalId =
  | 'h-huether-munich'
  | 'karl-schmitt-rummelsberg'
  | 'tm-ausbau-campus-ost'
  | 'gsh-gunzenhausen'
  | 'sedlmeyr-zielstattstrasse'
  | 'garzon-deisenhofen'

function isReferenceSignalId(value: string): value is ReferenceSignalId {
  return Object.hasOwn(REFERENCE_METADATA, value)
}

function metadataForId(signalId: string) {
  if (!isReferenceSignalId(signalId)) throw new Error('Unknown pinned reference signal: ' + signalId)
  return REFERENCE_METADATA[signalId]
}

function metadata(record: AwardSignal) {
  return metadataForId(record.id)
}

function companyAddress(company: CompanyRecord) {
  return company.facts.find((fact) => /adresse/i.test(fact.label))?.value ?? null
}

function entitlements({
  profiles,
  cadence,
  history,
  granted = 0,
  territory = 'single',
}: {
  profiles: number
  cadence: 'none' | 'weekly' | 'daily' | 'priority'
  history: number | null
  granted?: number
  territory?: 'single' | 'multiple' | 'expanded'
}) {
  return {
    max_active_icps: profiles,
    history_days: history,
    history_scope: history === null ? 'all_available' as const : 'window' as const,
    territory_mode: territory,
    max_territories_per_icp: territory === 'single' ? 1 : null,
    feed_access: true,
    detail_access: true,
    evidence_access: true,
    filter_level: 'basic' as const,
    export_level: 'none' as const,
    alert_cadence: cadence,
    granted_signals: granted,
  }
}

export const VISUAL_ME = {
  user_id: 'usr_reference_visual',
  email: 'claire@mueller-bauprodukte.example',
  account_id: 'acc_reference_visual',
  account_display_name: 'Müller Bauprodukte AG',
  locale: 'fr',
  onboarding_status: 'ready_for_signals',
  capabilities: { commercial_cockpit: false },
} satisfies Me

export const VISUAL_ICP = {
  target_icp_id: 'target-reference-menuiserie',
  label: 'Menuiserie intérieure',
  status: 'active',
  matching_revision: 1,
  plan_limit: null,
  customer_input: {
    offer_summary: 'Portes, quincaillerie et composants d’agencement\n\nSéries et composants pour les projets de menuiserie intérieure.',
    offers: ['materials_and_components'],
    secondary_offers: [],
    buyer_trades: ['interior_finishing'],
    secondary_buyer_trades: [],
    territories: ['DE'],
    minimum_contract_value: {
      currency: 'EUR',
      minimum_amount: 250000,
      maximum_amount: null,
    },
  },
  missing_fields: [],
  created_at: '2026-08-01T09:00:00+00:00',
  updated_at: '2026-08-29T09:00:00+00:00',
} satisfies TargetIcp

function toUnlockedItem(record: AwardSignal): UnlockedFeedItem {
  const meta = metadata(record)
  return {
    locked: false,
    signal_id: record.id,
    target_icp_id: VISUAL_ICP.target_icp_id,
    presentation: {
      artifact_id: `card-presentation-${record.id}-v1`,
      schema_version: 'card-presentation-v1',
      version: 1,
      status: 'PASS',
      published_at: '2026-08-29T08:00:00+00:00',
      content: {
        schema_version: 'card-presentation-v1',
        variant: 'FULL',
        headline: `${record.company.name} — ${record.shortTitle}`,
        award_summary: record.summary,
        commercial_importance: record.matchReasons[0]?.value ?? null,
        fit_reason: record.matchReasons[1]?.value ?? null,
        timing: record.matchReasons[2]?.value ?? null,
        recommended_action: record.questionsToVerify[0] ?? null,
        target_roles: ['SITE_PROCUREMENT_MANAGER'],
        fit_need_categories: ['materials_and_components'],
        unknowns: record.questionsToVerify.slice(0, 2),
        claims: [{
          claim_id: `claim-${record.id}-summary`,
          kind: 'FACT',
          text: record.summary,
          evidence_refs: [`notice:${record.notice}`],
          confidence: 'high',
        }],
      },
    },
    company: {
      name: record.company.name,
      country: meta.companyCountry,
      identifier: { scheme: 'REFERENCE', value: record.company.id },
    },
    event: {
      status: 'recent_award',
      type: 'recent_award',
      clock: 'award',
      date: record.contractDateIso,
      age_days: 15,
      headline: record.title,
      why_now: record.matchReasons[2]?.value ?? record.summary,
      award_date_note: 'La date d’attribution est publiée.',
      award_clock_status: 'recent',
      is_new_opportunity: true,
    },
    contract: {
      title: record.shortTitle,
      lot: null,
      lot_title: null,
      reference: record.notice,
      buyer: {
        name: record.buyer,
        country: meta.placeCountry,
        identifier: null,
      },
      amount: { value: meta.amount, currency: 'EUR' },
      cpv: record.cpv,
      location: {
        country: meta.placeCountry,
        locality: meta.locality,
        postal_code: null,
        subdivision_code: null,
      },
      dates: {
        award: record.contractDateIso,
        contract_notification: null,
        publication: meta.publication,
      },
    },
    analysis: {
      plausible_needs: {
        note: record.limit,
        items: record.scope.slice(0, 3).map((scope, index) => ({
          category: 'materials_and_components',
          label: scope.label,
          statement: record.questionsToVerify[index] ?? record.summary,
          confidence: 'medium',
          timing: 'near_term',
          timing_label: record.execution,
          targeted_by_your_profile: true,
        })),
      },
      fit: {
        label: record.matchLabel,
        target_icp_id: VISUAL_ICP.target_icp_id,
        target_icp_label: VISUAL_ICP.label,
        reasons: record.matchReasons.map((reason) => reason.value),
      },
    },
    source: {
      system: 'TED',
      country: meta.placeCountry,
      notice_id: record.notice,
      procedure_id: null,
      url: record.sourceUrl,
    },
  } satisfies UnlockedFeedItem
}

export const VISUAL_UNLOCKED_ITEMS = awardSignals.map(toUnlockedItem)

function toLockedItem(item: UnlockedFeedItem): LockedFeedItem {
  return {
    locked: true,
    signal_id: item.signal_id,
    target_icp_id: item.target_icp_id,
    unlock_required: 'paid_plan',
    event: {
      status: item.event.status,
      type: item.event.type,
      date: item.event.date,
      why_now: item.event.why_now,
      is_new_opportunity: item.event.is_new_opportunity,
    },
    context: {
      country: item.company.country,
      place_country: item.contract.location?.country ?? null,
      sector: 'Menuiserie intérieure',
      contract_magnitude: metadataForId(item.signal_id).magnitude,
      currency: item.contract.amount?.currency ?? null,
      plausible_need_count: item.analysis.plausible_needs.items.length,
    },
    headline: 'Un marché public vient d’être attribué.',
  } satisfies LockedFeedItem
}

export const VISUAL_LOCKED_ITEMS = VISUAL_UNLOCKED_ITEMS.slice(3).map(toLockedItem)

function toDetail(record: AwardSignal): UnlockedDetail {
  const item = toUnlockedItem(record)
  return {
    ...item,
    company_key: record.company.id,
    analysis: {
      ...item.analysis,
      contract_reading: {
        note: 'Lecture Kivou des pièces publiées.',
        summary: record.summary,
        contract_type: 'Travaux',
        sector: 'Menuiserie intérieure',
      },
    },
    evidence: {
      public_facts: record.scope.map((scope) => ({
        fact: 'published_contract_scope',
        label: scope.label,
        items: [{
          source_system: 'TED',
          source_kind: 'notice',
          notice_id: record.notice,
          procedure_id: null,
          url: record.sourceUrl,
          path: null,
          excerpt: scope.value + ' — ' + scope.label,
          retrieved_at: '2026-08-29T09:00:00+00:00',
        }],
      })),
      analysis_inputs: {
        note: record.limit,
        groups: record.questionsToVerify.map((question) => ({
          plausible_need: 'materials_and_components',
          label: question,
          items: [{
            source_system: 'TED',
            source_kind: 'notice',
            notice_id: record.notice,
            procedure_id: null,
            url: record.sourceUrl,
            path: null,
            excerpt: record.summary,
            retrieved_at: '2026-08-29T09:00:00+00:00',
          }],
        })),
      },
    },
    opportunity_id: 'opp-' + record.id,
    customer_ready: true,
    read_at: '2026-08-29T09:00:00+00:00',
    language: 'fr',
    interaction: null,
  } satisfies UnlockedDetail
}

export const VISUAL_DETAILS = awardSignals.map(toDetail)

function toCompanyProfile(record: AwardSignal): CompanyProfile {
  const item = toUnlockedItem(record)
  return {
    company_key: record.company.id,
    official_identity: {
      name: record.company.name,
      country: metadata(record).companyCountry,
      address: companyAddress(record.company),
      identifiers: [{ scheme: 'REFERENCE', value: record.company.id }],
      website_url: null,
      observed_at: '2026-08-29T09:00:00+00:00',
      source: 'public_notice',
    },
    related_signals: [{
      signal_id: record.id,
      contract_title: item.contract.title,
      amount: item.contract.amount,
      event: {
        status: item.event.status,
        date: item.event.date,
        headline: item.event.headline,
        why_now: item.event.why_now,
        award_date_note: item.event.award_date_note,
      },
      plausible_needs: item.analysis.plausible_needs.items.map((need) => ({
        label: need.label ?? record.matchLabel,
        statement: need.statement,
        timing_label: need.timing_label,
        reasoning: null,
      })),
      fit: {
        label: item.analysis.fit.label,
        reasons: item.analysis.fit.reasons,
      },
    }],
    coverage: {
      related_signals_complete: true,
      unavailable_fields: [],
    },
  } satisfies CompanyProfile
}

export const VISUAL_COMPANIES = awardSignals.map(toCompanyProfile)

export const VISUAL_CATALOGUE = {
  catalogue_version: 'reference-2026-08-29',
  billing_interval: 'month',
  currencies: ['chf'],
  plans: [
    {
      plan_code: 'discovery',
      purchasable: false,
      recommended: false,
      monthly_price: {},
      entitlements: entitlements({ profiles: 1, cadence: 'none', history: 0, granted: 3 }),
    },
    {
      plan_code: 'essential',
      purchasable: true,
      recommended: false,
      monthly_price: {
        chf: { amount_minor_units: 4900, currency: 'chf' },
      },
      entitlements: entitlements({ profiles: 1, cadence: 'weekly', history: 30 }),
    },
    {
      plan_code: 'pro',
      purchasable: true,
      recommended: true,
      monthly_price: {
        chf: { amount_minor_units: 9900, currency: 'chf' },
      },
      entitlements: entitlements({
        profiles: 3,
        cadence: 'daily',
        history: 365,
        territory: 'multiple',
      }),
    },
    {
      plan_code: 'scale',
      purchasable: true,
      recommended: false,
      monthly_price: {
        chf: { amount_minor_units: 19900, currency: 'chf' },
      },
      entitlements: entitlements({
        profiles: 10,
        cadence: 'priority',
        history: null,
        territory: 'expanded',
      }),
    },
  ],
} satisfies PlanCatalogue

export const VISUAL_PRO_STATUS = {
  plan_code: 'pro',
  offer_code: null,
  currency: 'chf',
  subscription_status: 'active',
  cancel_at_period_end: false,
  current_period_end: '2026-09-29T00:00:00+00:00',
  scheduled_cancellation_at: null,
  payment_issue: null,
  billing_action: 'manage_subscription',
  entitlements: entitlements({
    profiles: 3,
    cadence: 'daily',
    history: 365,
    territory: 'multiple',
  }),
  discovery: { granted_signal_count: 3, remaining_slots: 0, limit: 3 },
  target_icps_over_limit: [],
  policy: { billing: 'kivou-billing-v0.1' },
} satisfies BillingStatus

export const VISUAL_DISCOVERY_STATUS = {
  plan_code: 'discovery',
  offer_code: null,
  currency: null,
  subscription_status: null,
  cancel_at_period_end: false,
  current_period_end: null,
  scheduled_cancellation_at: null,
  payment_issue: null,
  billing_action: 'choose_plan',
  entitlements: entitlements({ profiles: 1, cadence: 'none', history: 0, granted: 3 }),
  discovery: { granted_signal_count: 3, remaining_slots: 0, limit: 3 },
  target_icps_over_limit: [],
  policy: { billing: 'kivou-billing-v0.1' },
} satisfies BillingStatus

export const VISUAL_NOTIFICATION_PREFERENCE = {
  email_enabled: true,
  notification_email: 'alertes@mueller-bauprodukte.example',
  updated_at: '2026-08-29T09:00:00+00:00',
} satisfies NotificationPreference

export type VisualScenario =
  | 'public-pricing'
  | 'auth'
  | 'connected-pro'
  | 'connected-discovery'

type ConnectedVisualScenario = Extract<
  VisualScenario,
  'connected-pro' | 'connected-discovery'
>

export const LOCAL_REFERENCE_ROUTES = [
  { golden: 'public-home', source: '/', local: '/', scenario: 'public-pricing' },
  { golden: 'public-product', source: '/produit', local: '/produit', scenario: 'public-pricing' },
  { golden: 'public-pricing', source: '/tarifs', local: '/tarifs', scenario: 'public-pricing' },
  { golden: 'public-signal', source: '/exemple-de-signal', local: '/exemple-de-signal', scenario: 'public-pricing' },
  { golden: 'public-contact', source: '/contact', local: '/contact', scenario: 'public-pricing' },
  { golden: 'public-legal', source: '/informations-legales', local: '/informations-legales', scenario: 'public-pricing' },
  { golden: 'dashboard-login', source: '/login', local: '/login', scenario: 'auth' },
  { golden: 'dashboard-signup', source: '/signup', local: '/signup', scenario: 'auth' },
  { golden: 'dashboard-overview', source: '/', local: '/app/dashboard', scenario: 'connected-pro' },
  { golden: 'dashboard-signals', source: '/signals?signal=tm-ausbau-campus-ost', local: '/app/signals/tm-ausbau-campus-ost', scenario: 'connected-discovery' },
  { golden: 'dashboard-companies', source: '/companies', local: '/app/companies', scenario: 'connected-pro' },
  { golden: 'dashboard-targeting', source: '/targeting', local: '/app/icps', scenario: 'connected-pro' },
  { golden: 'dashboard-account', source: '/settings', local: '/app/settings', scenario: 'connected-pro' },
] as const

function feedPage(scenario: ConnectedVisualScenario): FeedPage {
  const items = scenario === 'connected-discovery'
    ? [...VISUAL_UNLOCKED_ITEMS.slice(0, 3), ...VISUAL_LOCKED_ITEMS]
    : VISUAL_UNLOCKED_ITEMS
  return {
    items,
    total_returned: items.length,
    page: { limit: 20, offset: 0, has_more: false, scan_truncated: false },
    excluded: { without_display_name: 0, by_freshness: 0 },
    read_at: '2026-08-29T09:00:00+00:00',
    freshness: 'all',
    language: 'fr',
    plan_code: scenario === 'connected-discovery' ? 'discovery' : 'pro',
    policy: { feed: 'customer-feed-v0.1', recency: 'v1', paywall: 'kivou-paywall-v0.1' },
  } satisfies FeedPage
}

type VisualResponse = { status?: number; body: unknown }

function responseForConnected(
  scenario: ConnectedVisualScenario,
  key: string,
): VisualResponse | null {
  if (key === 'GET /me') return { body: VISUAL_ME }
  if (key === 'GET /target-icps') return { body: [VISUAL_ICP] }
  if (key === 'GET /billing/status') {
    return { body: scenario === 'connected-discovery' ? VISUAL_DISCOVERY_STATUS : VISUAL_PRO_STATUS }
  }
  if (key === 'GET /billing/plans') return { body: VISUAL_CATALOGUE }
  if (key === 'GET /notification-preferences') return { body: VISUAL_NOTIFICATION_PREFERENCE }
  if (key === 'GET /signals') return { body: feedPage(scenario) }

  const noteMatch = /^GET \/signals\/([^/]+)\/note$/.exec(key)
  if (noteMatch) {
    const signal = VISUAL_DETAILS.find((candidate) => candidate.signal_id === noteMatch[1])
    const allowed = scenario === 'connected-pro'
      || VISUAL_UNLOCKED_ITEMS.slice(0, 3).some((candidate) => candidate.signal_id === noteMatch[1])
    if (!signal || !allowed) return null
    return {
      body: { signal_id: signal.signal_id, note: null, updated_at: null },
    }
  }

  const detailMatch = /^GET \/signals\/([^/]+)$/.exec(key)
  if (detailMatch) {
    const detail = VISUAL_DETAILS.find((candidate) => candidate.signal_id === detailMatch[1])
    const allowed = scenario === 'connected-pro'
      || VISUAL_UNLOCKED_ITEMS.slice(0, 3).some((candidate) => candidate.signal_id === detailMatch[1])
    return detail && allowed ? { body: detail } : null
  }

  const companyMatch = /^GET \/companies\/([^/]+)$/.exec(key)
  if (companyMatch && scenario === 'connected-pro') {
    const company = VISUAL_COMPANIES.find((candidate) => candidate.company_key === companyMatch[1])
    return company ? { body: company } : null
  }

  return null
}

function visualResponse(scenario: VisualScenario, key: string): VisualResponse | null {
  switch (scenario) {
    case 'public-pricing':
    case 'auth':
      if (key === 'GET /me') {
        return { status: 401, body: { detail: { code: 'not_authenticated' } } }
      }
      if (key === 'GET /billing/plans') return { body: VISUAL_CATALOGUE }
      return null
    case 'connected-pro':
    case 'connected-discovery':
      return responseForConnected(scenario, key)
    default:
      return assertNever(scenario)
  }
}

function assertNever(value: never): never {
  throw new Error(`unknown visual scenario: ${String(value)}`)
}

const API_PREFIXES = [
  '/auth',
  '/me',
  '/target-icps',
  '/signals',
  '/companies',
  '/billing',
  '/notification-preferences',
] as const

function isApiPath(pathname: string) {
  return API_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(prefix + '/'))
}

export async function installReferenceApi(page: Page, scenario: VisualScenario) {
  const calls: Array<{ method: string; path: string }> = []
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (!isApiPath(url.pathname)) {
      await route.continue()
      return
    }
    const key = request.method() + ' ' + url.pathname
    calls.push({ method: request.method(), path: url.pathname })
    const response = visualResponse(scenario, key)
    if (!response) {
      calls.push({ method: request.method(), path: '/__unhandled__' })
      await route.fulfill({
        status: 501,
        contentType: 'application/json',
        body: JSON.stringify({ detail: { code: 'unhandled_visual_request', key } }),
      })
      return
    }
    await route.fulfill({
      status: response.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response.body),
    })
  })
  return calls
}

export async function normalizeConnectedText(page: Page) {
  await page.evaluate(async () => {
    const normalize = () => {
      const roots = document.querySelectorAll('.dashboard-provider, .auth-page, [role="dialog"]')
      for (const root of roots) {
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
        const nodes = []
        while (walker.nextNode()) nodes.push(walker.currentNode)
        const normalizedParents = new Set()
        for (const node of nodes) {
          if (!node.nodeValue?.trim()) continue
          const parent = node.parentNode
          const normalized = parent && normalizedParents.has(parent) ? '' : 'Texte'
          if (node.nodeValue !== normalized) node.nodeValue = normalized
          if (parent && normalized) normalizedParents.add(parent)
        }
        for (const field of root.querySelectorAll('input, textarea')) {
          if (field.getAttribute('placeholder') !== 'Texte') {
            field.setAttribute('placeholder', 'Texte')
          }
          if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
            if (field.value) field.value = ''
          }
        }
      }
    }

    let changed = false
    const observer = new MutationObserver(() => {
      changed = true
      normalize()
    })
    observer.observe(document.body, { childList: true, characterData: true, subtree: true })
    normalize()

    let stableFrames = 0
    for (let frame = 0; frame < 120 && stableFrames < 2; frame += 1) {
      changed = false
      await new Promise((resolve) => requestAnimationFrame(() => resolve(undefined)))
      if (changed) {
        normalize()
        stableFrames = 0
      } else {
        stableFrames += 1
      }
    }
    observer.disconnect()
    normalize()
    if (stableFrames < 2) throw new Error('connected text normalization did not stabilize')
  })
}
