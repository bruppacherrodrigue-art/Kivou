import type {
  BillingAction,
  CardPresentation,
  Money,
  Place,
  PlanCode,
} from '../../api/types'

export type SignalEventDateKind = 'award' | 'notification' | 'publication'

export interface EvidenceBoundLabel {
  label: string
  evidenceRefs: string[]
}

export interface SignalFactView {
  signalId: string
  locked: boolean
  eventDate: string | null
  eventDateKind: SignalEventDateKind
  buyerName: string | null
  awardedCompanyName: string | null
  primaryNeed: EvidenceBoundLabel | null
  fitReason: string | null
  presentation: CardPresentation | null
}

export interface SignalCardView extends SignalFactView {
  id: string
  companyName: string | null
  eventTitle: string | null
  amount: Money | null
  location: Place | null
  awardDate: string | null
  matchLabel: string | null
  matchReasons: string[]
  sourceSystem: string | null
  whyNow: string
}

export interface SignalDetailView extends SignalFactView {
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
    officialTitle: string | null
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
