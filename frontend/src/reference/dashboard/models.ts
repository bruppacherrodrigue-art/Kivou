import type {
  BillingAction,
  Money,
  Place,
  PlanCode,
} from '../../api/types'

export interface SignalCardView {
  id: string
  locked: boolean
  companyName: string | null
  eventTitle: string | null
  amount: Money | null
  location: Place | null
  eventDate: string | null
  awardDate: string | null
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
  title: string | null
  companyName: string | null
  companyKey: string | null
  companyCountry: string | null
  companyIdentifier: { scheme: string | null; value: string | null } | null
  targetProfileLabel: string | null
  sourceSystem: string | null
  summary: string | null
  brief: {
    whyNow: string
    offerCoverage: string | null
    functionToFind: string | null
    unknown: string | null
  }
  facts: {
    amount: Money | null
    awardDate: string | null
    execution: string | null
    buyer: string | null
    notice: string | null
    cpv: string | null
    sourceUrl: string | null
  }
  scope: { value: string; label: string }[]
  questions: string[]
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
