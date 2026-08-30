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
  SignalEventDateKind,
  TargetProfileView,
} from './models'

function eventDateKind(clock: string | null | undefined, status: string): SignalEventDateKind {
  if (clock === 'notification' || status === 'recently_notified_contract') {
    return 'notification'
  }
  if (
    clock === 'publication'
    || status === 'recently_published_award'
    || status === 'award_date_unknown'
  ) {
    return 'publication'
  }
  return 'award'
}

function concreteMatchReasons(reasons: string[]): string[] {
  return reasons.map((reason) => reason.trim()).filter(Boolean)
}

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
      eventDateKind: eventDateKind(undefined, _item.event.status),
      eventStatus: _item.event.status,
      awardDate: null,
      matchLabel: null,
      matchReasons: [],
      sourceSystem: null,
      whyNow: _item.event.why_now,
    }
  }

  const matchReasons = concreteMatchReasons(_item.analysis.fit.reasons)

  return {
    id: _item.signal_id,
    locked: false,
    companyName: _item.company.name,
    eventTitle: _item.contract.title,
    amount: _item.contract.amount,
    location: _item.contract.location,
    eventDate: _item.event.date,
    eventDateKind: eventDateKind(_item.event.clock, _item.event.status),
    eventStatus: _item.event.status,
    awardDate: _item.contract.dates.award,
    matchLabel: matchReasons.length > 0 ? _item.analysis.fit.label : null,
    matchReasons,
    sourceSystem: _item.source.system,
    whyNow: _item.event.why_now,
  }
}

export function toSignalCards(page: FeedPage): SignalCardView[] {
  return page.items.map(toSignalCard)
}

export function toSignalDetailView(detail: UnlockedDetail): SignalDetailView {
  const firstTargetedNeed = detail.analysis.plausible_needs.items.find(
    (need) => need.targeted_by_your_profile && Boolean(need.statement?.trim()),
  )

  return {
    id: detail.signal_id,
    title: detail.contract.title,
    companyName: detail.company.name,
    companyKey: detail.company_key ?? null,
    companyCountry: detail.company.country,
    companyIdentifier: detail.company.identifier,
    targetProfileLabel: detail.analysis.fit.target_icp_label,
    sourceSystem: detail.source.system,
    summary: detail.analysis.contract_reading?.summary ?? null,
    brief: {
      whyNow: detail.event.why_now,
      offerCoverage: firstTargetedNeed?.statement ?? null,
      functionToFind: null,
      unknown: detail.analysis.plausible_needs.note || null,
    },
    facts: {
      amount: detail.contract.amount,
      eventDate: detail.event.date,
      eventDateKind: eventDateKind(detail.event.clock, detail.event.status),
      awardDate: detail.contract.dates.award,
      execution: null,
      buyer: detail.contract.buyer?.name ?? null,
      notice: detail.source.notice_id,
      cpv: detail.contract.cpv,
      sourceUrl: detail.source.url,
    },
    // L'API ne publie pas de champ structuré « périmètre ». Les groupes
    // `public_facts` décrivent plusieurs natures de faits (attributaire,
    // montant, dates, acheteurs) et ne doivent pas être requalifiés ici.
    scope: [],
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
