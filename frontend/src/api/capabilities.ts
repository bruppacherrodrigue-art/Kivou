import type { Locale } from '../i18n'

/* Les capacités du produit au MVP — les décisions rendues visibles.
 *
 * CLOSEOUT §4 — cette liste était enfouie dans le composant de formulaire ICP,
 * où elle se lisait comme un détail de rendu. Elle n'en est pas un : c'est une
 * DÉCISION PRODUIT, et elle mérite un endroit nommé où la relire et la changer.
 *
 *     Ce que cette liste dit, et ce qu'elle ne dit pas
 *     ────────────────────────────────────────────────
 *     Elle dit : voici les territoires que l'onboarding propose au MVP.
 *     Elle NE dit PAS : voici les seuls pays présents dans TED.
 *
 * TED couvre l'Espace économique européen entier. La restriction est une
 * décision de périmètre produit — proposer un pays dont Kivou ne traite pas
 * encore les avis produirait un profil complet et un flux vide, ce qui est pire
 * qu'une liste courte et honnête.
 *
 * Le backend, lui, accepte tout code ISO 3166-1 alpha-2 : `TargetIcpInput`
 * n'impose aucune énumération sur `territories`. Élargir cette liste est donc
 * un changement purement frontend — mais il exige d'abord que la couverture
 * amont existe, et c'est pourquoi ce fichier n'invente aucune API de capacités.
 */

export interface Territory {
  /** ISO 3166-1 alpha-2, en majuscules — la forme exigée par le backend. */
  readonly code: string
  readonly fr: string
  readonly en: string
}

/** Les 10 territoires proposés à l'onboarding au MVP.
 *
 * Origine de la couverture : BOAMP et DECP pour la France, SIMAP pour la
 * Suisse, TED pour les autres. */
export const MVP_TERRITORIES: readonly Territory[] = [
  { code: 'FR', fr: 'France', en: 'France' },
  { code: 'CH', fr: 'Suisse', en: 'Switzerland' },
  { code: 'BE', fr: 'Belgique', en: 'Belgium' },
  { code: 'DE', fr: 'Allemagne', en: 'Germany' },
  { code: 'IT', fr: 'Italie', en: 'Italy' },
  { code: 'ES', fr: 'Espagne', en: 'Spain' },
  { code: 'LU', fr: 'Luxembourg', en: 'Luxembourg' },
  { code: 'NL', fr: 'Pays-Bas', en: 'Netherlands' },
  { code: 'AT', fr: 'Autriche', en: 'Austria' },
  { code: 'PT', fr: 'Portugal', en: 'Portugal' },
] as const

/** Les seuls codes que l'onboarding peut produire. */
export const MVP_TERRITORY_CODES: readonly string[] = MVP_TERRITORIES.map(
  (territory) => territory.code,
)

export function territoryLabel(territory: Territory, locale: Locale): string {
  return locale === 'fr' ? territory.fr : territory.en
}

/** Les devises de seuil proposées à l'onboarding.
 *
 * Elles ne décident de rien côté moteur : `MonetaryThreshold.currency` est un
 * champ libre de trois lettres. Ce sont les deux devises que Kivou facture et
 * que ses sources publient. */
export const MVP_THRESHOLD_CURRENCIES: readonly string[] = ['EUR', 'CHF'] as const
