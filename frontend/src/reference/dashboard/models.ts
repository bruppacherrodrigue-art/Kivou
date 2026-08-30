import type {
  BillingAction,
  CardPresentationClaimKind,
  CardPresentationConfidence,
  CardPresentationTargetRole,
  EventStatus,
  Money,
  Place,
  PlanCode,
} from '../../api/types'

export type SignalEventDateKind = 'award' | 'notification' | 'publication'

export interface SignalPresentationClaimView {
  id: string
  kind: CardPresentationClaimKind
  text: string
  evidenceRefs: string[]
  confidence: CardPresentationConfidence | null
}

export interface SignalPresentationView {
  artifactId: string
  version: number
  publishedAt: string
  mode: 'full' | 'factualFallback'
  headline: string
  awardSummary: string
  commercialImportance: string | null
  fitReason: string | null
  timing: string | null
  recommendedAction: string | null
  targetRoles: CardPresentationTargetRole[]
  fitNeedCategories: string[]
  unknowns: string[]
  claims: SignalPresentationClaimView[]
}

export interface SignalCardView {
  id: string
  locked: boolean
  companyName: string | null
  eventTitle: string | null
  amount: Money | null
  location: Place | null
  eventDate: string | null
  eventDateKind: SignalEventDateKind
  eventStatus: EventStatus
  awardDate: string | null
  presentation: SignalPresentationView | null
  matchLabel: string | null
  matchReasons: string[]
  sourceSystem: string | null
  whyNow: string
}

/** Carte strictement dédiée à la vue d'ensemble.
 *
 * Les champs narratifs proviennent uniquement de l'artefact Card
 * Intelligence publié. Le titre brut du marché et les déductions historiques
 * du feed n'entrent volontairement pas dans ce modèle.
 */
export interface OverviewAwardCardView {
  id: string
  locked: boolean
  companyName: string | null
  teaserHeadline: string | null
  headline: string | null
  awardSummary: string | null
  commercialImportance: string | null
  fitReason: string | null
  timing: string | null
  recommendedAction: string | null
  presentationVariant: 'FULL' | 'FACTUAL_FALLBACK' | null
  amount: Money | null
  location: Place | null
  awardDate: string | null
  sourceSystem: string | null
}

export interface SignalDetailView {
  id: string
  companyName: string | null
  companyKey: string | null
  companyCountry: string | null
  companyIdentifier: { scheme: string | null; value: string | null } | null
  sourceSystem: string | null
  presentation: SignalPresentationView | null
  facts: {
    amount: Money | null
    location: Place | null
    eventDate: string | null
    eventDateKind: SignalEventDateKind
    awardDate: string | null
    execution: string | null
    buyer: string | null
    officialTitle: string | null
    notice: string | null
    cpv: string | null
    sourceUrl: string | null
  }
}

export interface TargetProfileView {
  id: string
  label: string
  firstTerritory: string | null
  active: boolean
}

export interface BillingAccessView {
  planCode: PlanCode
  billingAction: BillingAction
  subscriptionStatus: string | null
}

export interface CompanySummaryView {
  key: string
  name: string
  country: string | null
  address: string | null
  websiteUrl: string | null
  relatedSignalCount: number
}
