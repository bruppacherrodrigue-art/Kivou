/* Le signal réel exposé publiquement, en démonstration produit.
 *
 * Pourquoi ce fichier existe, et pourquoi il est écrit à la main
 * ──────────────────────────────────────────────────────────────
 * La surface publique ne doit appeler AUCUN point d'entrée client. Elle ne
 * peut donc pas lire un signal dans l'API : il faut une donnée versionnée,
 * lisible en revue, et dont chaque champ se vérifie contre une source
 * officielle. C'est le rôle de ce module.
 *
 * C'est une PROJECTION explicite, pas une copie
 * ─────────────────────────────────────────────
 * Le corpus interne porte aussi un profil de ciblage, un score, une bande et
 * un verdict de benchmark. Rien de tout cela n'a de sens pour un visiteur, et
 * l'exposer reviendrait à publier la mécanique interne de Kivou. Seuls les
 * champs ci-dessous sont repris, un par un et à la main. Exporter l'objet brut
 * aurait fait fuiter le reste au premier copier-coller.
 *
 * Origine, vérifiable ligne à ligne
 * ─────────────────────────────────
 *   corpus   tests/fixtures/signal100/signal100_corpus.json
 *   signal   ffd0dfe063ba123f0fdfc74f1afa06fb2fd5b41dea405425230cd5e350e47353
 *   avis     TED 568562-2026
 *
 * Chacun des faits ci-dessous a été confronté au XML officiel de l'avis,
 * récupéré en direct : gagnant, acheteur, montant, les trois dates, CPV,
 * référence de contrat, identifiant d'entreprise, et jusqu'aux quantités
 * publiées. Aucune valeur n'est reformulée, arrondie ni traduite.
 *
 * Ce que ce signal n'a PAS
 * ────────────────────────
 * Aucune exigence d'exécution validée. L'analyse repose sur les seules
 * métadonnées de l'avis — `metadata_fallback`. Le descriptif publié dans
 * l'avis n'est PAS un passage de cahier des charges et ne doit jamais être
 * présenté comme tel. L'interface l'affiche explicitement plutôt que de le
 * masquer : une couverture documentaire absente est un fait produit, pas une
 * imperfection à cacher.
 */

/** Un fait publié par la source, avec le chemin qui permet de le retrouver. */
export interface PublicDemoEvidence {
  /** Chemin du champ dans le document source. */
  readonly path: string
  /** Valeur telle que publiée. */
  readonly rawValue: string
}

export interface PublicDemoSignal {
  readonly noticeId: string
  readonly sourceSystem: 'ted'
  readonly sourceUrl: string
  /** Date à laquelle les faits ont été confrontés à la source officielle. */
  readonly lastVerifiedAt: string
  readonly retrievedAt: string
  readonly winner: {
    readonly legalName: string
    readonly country: string
    readonly address: string
    readonly identifier: { readonly scheme: string; readonly value: string }
  }
  readonly buyer: { readonly legalName: string; readonly country: string }
  readonly contract: {
    readonly title: string
    readonly reference: string
    readonly cpv: string
    readonly amount: string
    readonly currency: string
    readonly locality: string
    readonly postalCode: string
    readonly country: string
    /** Quantités telles que l'avis les publie. Ce n'est pas un extrait de
     *  cahier des charges : c'est le descriptif de l'avis d'attribution. */
    readonly publishedQuantities: readonly string[]
  }
  readonly timing: {
    readonly awardDate: string
    readonly signatureDate: string
    readonly startDate: string
    readonly endDate: string
    readonly publishedAt: string
  }
  readonly documentary: {
    /** `metadata_fallback` : aucune pièce de marché validée n'alimente
     *  l'analyse de ce signal. */
    readonly mode: 'metadata_fallback'
    readonly validatedRequirement: false
  }
  /** Le besoin plausible, repris VERBATIM du corpus. Ni reformulé, ni
   *  renforcé : durcir la formulation transformerait une hypothèse en
   *  promesse. */
  readonly need: {
    readonly category: 'materials_or_components'
    readonly statement: string
    readonly reasoning: string
    readonly timing: 'near_term'
    readonly externalisability: 'external_plausible'
  }
  readonly evidence: readonly PublicDemoEvidence[]
}

export const publicDemoSignal: PublicDemoSignal = {
  noticeId: '568562-2026',
  sourceSystem: 'ted',
  sourceUrl: 'https://ted.europa.eu/en/notice/568562-2026/xml',
  lastVerifiedAt: '2026-08-20',
  retrievedAt: '2026-08-17T13:43:59.417748Z',

  winner: {
    legalName: 'H. Hüther GmbH',
    country: 'DE',
    address: 'Graseweg 8, 34346 Hedemünden',
    identifier: { scheme: 'TED-BT-501', value: 'DE115302781' },
  },

  buyer: { legalName: 'Staatl. Bauamt München 1', country: 'DE' },

  contract: {
    // Orthographe de la source : TED publie les tréma en translittération.
    // Corriger « Innentueren » en « Innentüren » serait réécrire l'avis.
    title: 'Tischlerarbeiten Innentueren und Moebel',
    reference: '26-000.723.722',
    cpv: '45420000',
    amount: '5219043.35',
    currency: 'EUR',
    locality: 'München',
    postalCode: '80335',
    country: 'DE',
    publishedQuantities: [
      'Holzzarge Holzblatt : 497',
      'Stahlzarge Holzblatt : 234',
      'Sockelleisten : 5 485 m',
      'Holzwandverkleidung : 425 m²',
      'Verglasungen : 24',
      'Teeküchen : 13',
    ],
  },

  timing: {
    awardDate: '2026-08-14',
    signatureDate: '2026-08-14',
    startDate: '2026-10-28',
    endDate: '2027-10-29',
    publishedAt: '2026-08-17',
  },

  documentary: { mode: 'metadata_fallback', validatedRequirement: false },

  need: {
    category: 'materials_or_components',
    statement: "Un approvisionnement en matériaux ou composants pourrait accompagner l'exécution des travaux.",
    reasoning:
      'La nature des travaux — bâtiment, installation technique ou finition — consomme des matériaux et des composants en volume : des achats d’approvisionnement sont plausibles auprès de négoces ou de fabricants.',
    timing: 'near_term',
    externalisability: 'external_plausible',
  },

  // Seules les preuves dont le corpus publie une VALEUR sont reprises. Le
  // corpus porte aussi un renvoi vers `cbc:Description` dont la valeur est
  // nulle : l'afficher aurait obligé à inventer son contenu.
  evidence: [
    {
      path: 'cac:ProcurementProject/cac:MainCommodityClassification/cbc:ItemClassificationCode',
      rawValue: '45420000',
    },
    { path: 'value', rawValue: '5219043.35 EUR' },
    { path: 'lot.identifier', rawValue: 'LOT-0000' },
  ],
}
