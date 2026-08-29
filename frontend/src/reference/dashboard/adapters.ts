import type {
  BillingStatus,
  CompanyProfile,
  FeedItem,
  FeedPage,
  TargetIcp,
  UnlockedDetail,
} from '../../api/types'
import type {
  BillingAccessView,
  CompanySummaryView,
  SignalCardView,
  SignalDetailView,
  TargetProfileView,
} from './models'

export function toSignalCard(_item: FeedItem): SignalCardView {
  if (_item.locked) {
    return {
      id: _item.signal_id,
      locked: true,
      companyName: null,
      eventTitle: _item.headline,
      amount: null,
      location: null,
      eventDate: _item.event.date,
      matchLabel: null,
      whyNow: _item.event.why_now,
    }
  }

  return {
    id: _item.signal_id,
    locked: false,
    companyName: _item.company.name,
    eventTitle: _item.contract.title,
    amount: _item.contract.amount,
    location: _item.contract.location,
    eventDate: _item.event.date,
    matchLabel: _item.analysis.fit.label,
    whyNow: _item.event.why_now,
  }
}

export function toSignalCards(page: FeedPage): SignalCardView[] {
  return page.items.map(toSignalCard)
}

export function toSignalDetailView(detail: UnlockedDetail): SignalDetailView {
  const firstNeed = detail.analysis.plausible_needs.items[0]
  const scope = detail.evidence.public_facts.flatMap((fact) =>
    fact.items.flatMap((item) =>
      item.excerpt === null ? [] : [{ value: item.excerpt, label: fact.label }],
    ),
  )

  return {
    id: detail.signal_id,
    title: detail.contract.title,
    companyName: detail.company.name,
    companyKey: detail.company_key ?? null,
    summary: detail.analysis.contract_reading?.summary ?? null,
    brief: {
      whyNow: detail.event.why_now,
      offerCoverage: firstNeed?.statement ?? null,
      functionToFind: null,
      unknown: detail.analysis.plausible_needs.note || null,
    },
    facts: {
      amount: detail.contract.amount,
      concludedAt: detail.contract.dates.award,
      execution: null,
      buyer: detail.contract.buyer?.name ?? null,
      notice: detail.source.notice_id,
      cpv: detail.contract.cpv,
      sourceUrl: detail.source.url,
    },
    scope,
    questions: [],
  }
}

export function toTargetProfileView(profile: TargetIcp): TargetProfileView {
  return {
    id: profile.target_icp_id,
    label: profile.label,
    firstTerritory: profile.customer_input.territories[0] ?? null,
    active: profile.status === 'active',
  }
}

export function toBillingAccessView(status: BillingStatus): BillingAccessView {
  return {
    planCode: status.plan_code,
    billingAction: status.billing_action,
    subscriptionStatus: status.subscription_status,
  }
}

export function toCompanySummary(profile: CompanyProfile): CompanySummaryView {
  return {
    key: profile.company_key,
    name: profile.official_identity.name,
    country: profile.official_identity.country,
    address: profile.official_identity.address,
    websiteUrl: profile.official_identity.website_url,
    relatedSignalCount: profile.related_signals.length,
  }
}
