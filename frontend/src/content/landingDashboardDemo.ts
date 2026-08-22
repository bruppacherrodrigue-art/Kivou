import { publicDemoSignal } from './publicDemoSignal'
import type { LocalisedText } from './publicDemoSignal'

/* Fixture publique pour la capture du dashboard marketing.
 *
 * Elle agrège uniquement des faits publics déjà utilisés par la démonstration
 * et trois signaux de feed très résumés issus de `tests/fixtures/signal100`.
 * Aucune donnée de compte, aucun contact personnel et aucun identifiant interne
 * ne sont exposés ici.
 */

export interface DemoFeedSignal {
  readonly company: string
  readonly event: LocalisedText
  readonly amount: string
  readonly region: LocalisedText
  readonly freshness: LocalisedText
  readonly fit: LocalisedText
  readonly reason: LocalisedText
}

export const dashboardDemoFeed: readonly DemoFeedSignal[] = [
  {
    company: publicDemoSignal.winner.legalName,
    event: { fr: 'Marché de menuiserie intérieure', en: 'Interior joinery contract' },
    amount: '5,22 M€',
    region: { fr: 'Munich, Allemagne', en: 'Munich, Germany' },
    freshness: { fr: 'Attribué le 14 août 2026', en: 'Awarded 14 August 2026' },
    fit: { fr: 'Adéquation forte', en: 'Strong fit' },
    reason: {
      fr: 'Portes, plinthes, revêtement bois et kitchenettes dans votre territoire.',
      en: 'Doors, skirting, timber cladding and kitchenettes in your territory.',
    },
  },
  {
    company: 'Heinrich Würfel Metallbau GmbH',
    event: {
      fr: 'Fassadensanierung Kreisberufsschulzentrum Aalen',
      en: 'Facade refurbishment at Kreisberufsschulzentrum Aalen',
    },
    amount: '5,25 M€',
    region: { fr: 'Allemagne', en: 'Germany' },
    freshness: { fr: 'Publié le 17 août 2026', en: 'Published 17 August 2026' },
    fit: { fr: 'Signal compatible', en: 'Compatible signal' },
    reason: {
      fr: 'Marché de métallurgie et façade dans une zone industrielle ciblée.',
      en: 'Metalwork and facade contract in a targeted industrial area.',
    },
  },
  {
    company: 'GOLDBECK Süd GmbH, Niederlassung Bodensee',
    event: {
      fr: 'Neubau eines Parkhauses für Mitarbeitende',
      en: 'New employee car park construction',
    },
    amount: '11,56 M€',
    region: { fr: 'Allemagne', en: 'Germany' },
    freshness: { fr: 'Publié le 17 août 2026', en: 'Published 17 August 2026' },
    fit: { fr: 'Signal à examiner', en: 'Signal to review' },
    reason: {
      fr: 'Construction neuve et volumes compatibles avec des fournisseurs chantier.',
      en: 'New construction and scale compatible with worksite suppliers.',
    },
  },
  {
    company: 'SPIE ICS',
    event: {
      fr: "Prestations d'infogérance systèmes et réseaux",
      en: 'Managed systems and network services',
    },
    amount: '24,53 M€',
    region: { fr: 'France', en: 'France' },
    freshness: { fr: 'Publié le 17 août 2026', en: 'Published 17 August 2026' },
    fit: { fr: 'Autre profil', en: 'Different profile' },
    reason: {
      fr: 'Exemple de signal visible dans le feed, filtrable par profil.',
      en: 'Example feed signal that can be filtered by target profile.',
    },
  },
] as const

export const dashboardDemoVolumes = [
  { value: '497', label: { fr: 'portes et huisseries bois', en: 'timber doors and frames' } },
  { value: '234', label: { fr: 'huisseries acier et portes bois', en: 'steel frames and timber doors' } },
  { value: '5 485 m', label: { fr: 'plinthes', en: 'skirting boards' } },
  { value: '425 m²', label: { fr: 'revêtement bois', en: 'timber wall cladding' } },
  { value: '24', label: { fr: 'vitrages', en: 'glazed elements' } },
  { value: '13', label: { fr: 'kitchenettes', en: 'kitchenettes' } },
] as const

export const dashboardDemoSourceNotes = {
  awardNotice: publicDemoSignal.sourceUrl,
  contactSource: publicDemoSignal.winner.contactVerificationSource,
} as const
