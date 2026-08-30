import type {
  BillingStatus,
  CardPresentation,
  CardPresentationContent,
  CompanyProfile,
  FeedItem,
  FeedPage,
  TargetIcp,
  UnlockedDetail,
} from '../../api/types'
import type {
  BillingAccessView,
  CompanySummaryView,
  OverviewAwardCardView,
  SignalCardView,
  SignalDetailView,
  TargetProfileView,
} from './models'

function publishedPresentationContent(
  presentation: CardPresentation | null,
): CardPresentationContent | null {
  if (!presentation || !isRecord(presentation) || !isRecord(presentation.content)) {
    return null
  }

  const candidate = presentation as unknown as Record<string, unknown>
  const content = candidate.content as Record<string, unknown>
  const targetRoles = content.target_roles
  const fitNeedCategories = content.fit_need_categories
  const unknowns = content.unknowns
  const claims = content.claims
  const hasCommonShape = (
    candidate.schema_version === 'card-presentation-v1'
    && content.schema_version === 'card-presentation-v1'
    && hasText(content.headline)
    && hasText(content.award_summary)
    && Array.isArray(targetRoles)
    && Array.isArray(fitNeedCategories)
    && Array.isArray(unknowns)
    && Array.isArray(claims)
  )
  if (!hasCommonShape) return null
  const publishedTargetRoles = targetRoles as unknown[]
  const publishedFitNeedCategories = fitNeedCategories as unknown[]
  const publishedClaims = claims as unknown[]

  if (candidate.status === 'PASS' && content.variant === 'FULL') {
    const commercialFields = [
      content.commercial_importance,
      content.fit_reason,
      content.timing,
      content.recommended_action,
    ]
    return commercialFields.every(hasText)
      ? content as unknown as CardPresentationContent
      : null
  }

  if (candidate.status === 'FALLBACK' && content.variant === 'FACTUAL_FALLBACK') {
    const hasNoCommercialInference = (
      content.commercial_importance === null
      && content.fit_reason === null
      && content.timing === null
      && content.recommended_action === null
      && publishedTargetRoles.length === 0
      && publishedFitNeedCategories.length === 0
      && publishedClaims.every((claim) => isRecord(claim) && claim.kind === 'FACT')
    )
    return hasNoCommercialInference
      ? content as unknown as CardPresentationContent
      : null
  }

  return null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasText(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

export function toOverviewAwardCard(item: FeedItem): OverviewAwardCardView {
  if (item.locked) {
    return {
      id: item.signal_id,
      locked: true,
      companyName: null,
      teaserHeadline: item.headline,
      headline: null,
      awardSummary: null,
      commercialImportance: null,
      fitReason: null,
      timing: null,
      recommendedAction: null,
      presentationVariant: null,
      amount: null,
      location: null,
      awardDate: null,
      sourceSystem: null,
    }
  }

  const content = publishedPresentationContent(item.presentation)

  return {
    id: item.signal_id,
    locked: false,
    companyName: item.company.name,
    teaserHeadline: null,
    headline: content?.headline ?? null,
    awardSummary: content?.award_summary ?? null,
    commercialImportance: content?.commercial_importance ?? null,
    fitReason: content?.fit_reason ?? null,
    timing: content?.timing ?? null,
    recommendedAction: content?.recommended_action ?? null,
    presentationVariant: content?.variant ?? null,
    amount: item.contract.amount,
    location: item.contract.location,
    awardDate: item.contract.dates.award,
    sourceSystem: item.source.system,
  }
}

export function toOverviewAwardCards(page: FeedPage): OverviewAwardCardView[] {
  return page.items.map(toOverviewAwardCard)
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
      awardDate: null,
      matchLabel: null,
      matchReasons: [],
      sourceSystem: null,
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
    awardDate: _item.contract.dates.award,
    matchLabel: _item.analysis.fit.label,
    matchReasons: _item.analysis.fit.reasons,
    sourceSystem: _item.source.system,
    whyNow: _item.event.why_now,
  }
}

export function toSignalCards(page: FeedPage): SignalCardView[] {
  return page.items.map(toSignalCard)
}

export function toSignalDetailView(detail: UnlockedDetail): SignalDetailView {
  const firstNeed = detail.analysis.plausible_needs.items[0]

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
      offerCoverage: firstNeed?.statement ?? null,
      functionToFind: null,
      unknown: detail.analysis.plausible_needs.note || null,
    },
    facts: {
      amount: detail.contract.amount,
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
