import type {
  BillingAction,
  Money,
  Place,
  PlanCode,
} from '../../api/types'

export type SignalEventDateKind = 'award' | 'notification' | 'publication' | 'unknown'

/** Projection dédiée au Dashboard.
 *
 * Les textes éditoriaux proviennent exclusivement de l'artefact publié. Les
 * faits structurés restent séparés et le titre administratif n'entre jamais
 * dans cette vue.
 */
export interface OverviewAwardCardView {
  id: string
  locked: boolean
  presentationArtifactId: string | null
  companyName: string | null
  buyerName: string | null
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
  eventDate: string | null
  eventDateKind: SignalEventDateKind
  sourceSystem: string | null
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
