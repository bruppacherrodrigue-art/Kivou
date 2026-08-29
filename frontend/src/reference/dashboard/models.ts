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
  matchLabel: string | null
  whyNow: string
}

export interface SignalDetailView {
  id: string
  title: string | null
  companyName: string | null
  companyKey: string | null
  summary: string | null
  brief: {
    whyNow: string
    offerCoverage: string | null
    functionToFind: string | null
    unknown: string | null
  }
  facts: {
    amount: Money | null
    concludedAt: string | null
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
