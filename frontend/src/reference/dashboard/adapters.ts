import type {
  BillingStatus,
  CompanyProfile,
  EventStatus,
  EvidenceItem,
  FeedItem,
  FeedPage,
  SignalEventClock,
  TargetIcp,
  UnlockedDetail,
} from '../../api/types'
import type {
  BillingAccessView,
  CompanySummaryView,
  EvidenceBoundLabel,
  SignalCardView,
  SignalDetailView,
  SignalEventDateKind,
  TargetProfileView,
} from './models'

const EVENT_DATE_KIND_BY_CLOCK = {
  award: 'award',
  notification: 'notification',
  publication: 'publication',
} as const satisfies Record<SignalEventClock, SignalEventDateKind>

const EVENT_CLOCK_BY_STATUS = {
  recent_award: 'award',
  recently_notified_contract: 'notification',
  recently_published_award: 'publication',
  aging_award: 'award',
  stale_award: 'award',
  award_date_unknown: 'publication',
  invalid_award_date: 'award',
} as const satisfies Record<EventStatus, SignalEventClock>

/** Le type de date est celui choisi par le backend, jamais déduit du titre. */
export function eventDateKind(
  clock: SignalEventClock,
  status: EventStatus,
): SignalEventDateKind {
  if (EVENT_CLOCK_BY_STATUS[status] !== clock) {
    throw new Error(`Horloge d'événement incohérente pour le statut ${status}`)
  }
  return EVENT_DATE_KIND_BY_CLOCK[clock]
}

export function concreteMatchReasons(reasons: readonly string[]): string[] {
  return reasons.map((reason) => reason.trim()).filter(Boolean)
}

export function toSignalCard(item: FeedItem): SignalCardView {
  if (item.locked) {
    const clock = EVENT_CLOCK_BY_STATUS[item.event.status]
    return {
      signalId: item.signal_id,
      id: item.signal_id,
      locked: true,
      companyName: null,
      awardedCompanyName: null,
      buyerName: null,
      eventTitle: item.headline,
      amount: null,
      location: null,
      eventDate: item.event.date,
      eventDateKind: eventDateKind(clock, item.event.status),
      awardDate: null,
      matchLabel: null,
      matchReasons: [],
      primaryNeed: null,
      fitReason: null,
      presentation: null,
      sourceSystem: null,
      whyNow: item.event.why_now,
    }
  }

  const presentation = item.presentation
  const matchReasons = concreteMatchReasons(item.analysis.fit.reasons)
  const fitReason = matchReasons[0] ?? null
  return {
    signalId: item.signal_id,
    id: item.signal_id,
    locked: false,
    companyName: item.company.name,
    awardedCompanyName: item.company.name,
    buyerName: item.contract.buyer?.name ?? null,
    eventTitle: presentation?.content.headline ?? null,
    amount: item.contract.amount,
    location: item.contract.location,
    eventDate: item.event.date,
    eventDateKind: eventDateKind(item.event.clock, item.event.status),
    awardDate: item.contract.dates.award,
    matchLabel: fitReason,
    matchReasons,
    primaryNeed: null,
    fitReason,
    presentation,
    sourceSystem: item.source.system,
    whyNow: item.event.why_now,
  }
}

export function toSignalCards(page: FeedPage): SignalCardView[] {
  return page.items.map(toSignalCard)
}

export function toSignalDetailView(detail: UnlockedDetail): SignalDetailView {
  const primaryNeed = firstEvidenceBoundTargetedNeed(detail)
  const presentation = detail.presentation
  const fitReason = concreteMatchReasons(detail.analysis.fit.reasons)[0] ?? null

  return {
    signalId: detail.signal_id,
    id: detail.signal_id,
    locked: false,
    eventDate: detail.event.date,
    eventDateKind: eventDateKind(detail.event.clock, detail.event.status),
    buyerName: detail.contract.buyer?.name ?? null,
    awardedCompanyName: detail.company.name,
    primaryNeed,
    fitReason,
    presentation,
    title: presentation?.content.headline ?? null,
    companyName: detail.company.name,
    companyKey: detail.company_key ?? null,
    companyCountry: detail.company.country,
    companyIdentifier: detail.company.identifier,
    targetProfileLabel: detail.analysis.fit.target_icp_label,
    sourceSystem: detail.source.system,
    summary: presentation?.content.award_summary ?? null,
    brief: {
      whyNow: detail.event.why_now,
      offerCoverage: primaryNeed?.label ?? null,
      functionToFind: null,
      unknown: detail.analysis.plausible_needs.note || null,
    },
    facts: {
      amount: detail.contract.amount,
      awardDate: detail.contract.dates.award,
      execution: null,
      buyer: detail.contract.buyer?.name ?? null,
      officialTitle: detail.contract.title,
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

function firstEvidenceBoundTargetedNeed(detail: UnlockedDetail): EvidenceBoundLabel | null {
  for (const need of detail.analysis.plausible_needs.items) {
    const label = need.label?.trim() ?? ''
    if (!need.targeted_by_your_profile || !label || !need.category) continue

    const evidenceRefs = detail.evidence.analysis_inputs.groups
      .filter((group) => group.plausible_need === need.category)
      .flatMap((group) => group.items)
      .map(canonicalEvidenceRef)
      .filter((reference): reference is string => reference !== null)
    const uniqueRefs = [...new Set(evidenceRefs)]
    if (uniqueRefs.length > 0) return { label, evidenceRefs: uniqueRefs }
  }
  return null
}

function canonicalEvidenceRef(item: EvidenceItem): string | null {
  const url = item.url?.trim() ?? ''
  const path = item.path?.trim() ?? ''
  if (url) {
    return `evidence:url:${encodeURIComponent(url)}`
      + (path ? `:path:${encodeURIComponent(path)}` : '')
  }

  const sourceSystem = item.source_system?.trim() ?? ''
  const noticeId = item.notice_id?.trim() ?? ''
  const procedureId = item.procedure_id?.trim() ?? ''
  if (!sourceSystem || (!noticeId && !procedureId)) return null

  return [
    `evidence:source:${encodeURIComponent(sourceSystem)}`,
    noticeId ? `notice:${encodeURIComponent(noticeId)}` : null,
    procedureId ? `procedure:${encodeURIComponent(procedureId)}` : null,
    path ? `path:${encodeURIComponent(path)}` : null,
  ].filter((part): part is string => part !== null).join(':')
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
