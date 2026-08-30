import type {
  BillingStatus,
  CardPresentationTargetRole,
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
  SignalEventDateKind,
  SignalPresentationClaimView,
  SignalPresentationView,
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

const TARGET_ROLES = new Set<CardPresentationTargetRole>([
  'PROCUREMENT_MANAGER',
  'SITE_PROCUREMENT_MANAGER',
  'PROJECT_MANAGER',
  'WORKS_MANAGER',
  'SUPPLY_MANAGER',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function boundedText(value: unknown, maxLength: number): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed && trimmed.length <= maxLength ? trimmed : null
}

function boundedTextList(value: unknown, maxItems: number, maxLength: number): string[] | null {
  if (!Array.isArray(value) || value.length > maxItems) return null
  const items = value.map((item) => boundedText(item, maxLength))
  return items.every((item): item is string => item !== null) ? items : null
}

function safeHttpsUrl(value: string | null): string | null {
  if (!value) return null
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'https:' ? parsed.toString() : null
  } catch {
    return null
  }
}

function presentationClaim(claim: unknown): SignalPresentationClaimView | null {
  if (!isRecord(claim)) return null
  const id = boundedText(claim.claim_id, 64)
  const text = boundedText(claim.text, 420)
  const evidenceRefs = boundedTextList(claim.evidence_refs, 16, 256)
  const kind = claim.kind
  const confidence = claim.confidence
  if (
    !id
    || !/^[A-Z][A-Z0-9_]{0,63}$/.test(id)
    || !text
    || !evidenceRefs
    || (kind !== 'FACT' && kind !== 'INFERENCE' && kind !== 'RECOMMENDATION')
  ) return null
  if (evidenceRefs.length === 0) {
    return null
  }
  if (
    kind === 'INFERENCE'
    && confidence !== 'high'
    && confidence !== 'medium'
    && confidence !== 'low'
  ) {
    return null
  }
  if (confidence !== null && confidence !== 'high' && confidence !== 'medium' && confidence !== 'low') {
    return null
  }
  return {
    id,
    kind,
    text,
    evidenceRefs,
    confidence,
  }
}

/**
 * Valide uniquement la forme publiée. Un payload absent ou incohérent devient
 * `null`; cet adaptateur ne reconstruit jamais un récit depuis le signal brut.
 */
export function toSignalPresentationView(
  presentation: unknown,
): SignalPresentationView | null {
  if (!isRecord(presentation) || !isRecord(presentation.content)) return null
  const content = presentation.content
  if (
    presentation.schema_version !== 'card-presentation-v1'
    || content.schema_version !== 'card-presentation-v1'
    || !boundedText(presentation.artifact_id, 64)
    || !Number.isInteger(presentation.version)
    || (presentation.version as number) < 1
    || !boundedText(presentation.published_at, 64)
    || Number.isNaN(Date.parse(presentation.published_at as string))
  ) return null

  const headline = boundedText(content.headline, 160)
  const awardSummary = boundedText(content.award_summary, 420)
  const unknowns = boundedTextList(content.unknowns, 8, 240)
  const fitNeedCategories = boundedTextList(content.fit_need_categories, 8, 256)
  const targetRoles = Array.isArray(content.target_roles)
    && content.target_roles.length <= 6
    && content.target_roles.every(
      (role): role is CardPresentationTargetRole =>
        typeof role === 'string' && TARGET_ROLES.has(role as CardPresentationTargetRole),
    )
    ? content.target_roles
    : null
  const claims = Array.isArray(content.claims) && content.claims.length > 0 && content.claims.length <= 12
    ? content.claims.map(presentationClaim)
    : null
  if (
    !headline
    || !awardSummary
    || !unknowns
    || !fitNeedCategories
    || !targetRoles
    || !claims
    || claims.some((claim) => claim === null)
  ) return null
  const validClaims = claims.filter(
    (claim): claim is SignalPresentationClaimView => claim !== null,
  )

  if (presentation.status === 'FALLBACK' && content.variant === 'FACTUAL_FALLBACK') {
    if (
      content.commercial_importance !== null
      || content.fit_reason !== null
      || content.timing !== null
      || content.recommended_action !== null
      || targetRoles.length > 0
      || fitNeedCategories.length > 0
      || validClaims.some((claim) => claim.kind !== 'FACT')
    ) return null
    return {
      artifactId: presentation.artifact_id as string,
      version: presentation.version as number,
      publishedAt: presentation.published_at as string,
      mode: 'factualFallback',
      headline,
      awardSummary,
      commercialImportance: null,
      fitReason: null,
      timing: null,
      recommendedAction: null,
      targetRoles: [],
      fitNeedCategories: [],
      unknowns,
      claims: validClaims,
    }
  }

  if (presentation.status !== 'PASS' || content.variant !== 'FULL') return null
  const commercialImportance = boundedText(content.commercial_importance, 420)
  const fitReason = boundedText(content.fit_reason, 420)
  const timing = boundedText(content.timing, 320)
  const recommendedAction = boundedText(content.recommended_action, 320)
  if (
    !commercialImportance
    || !fitReason
    || !timing
    || !recommendedAction
    || targetRoles.length === 0
    || fitNeedCategories.length === 0
  ) return null

  return {
    artifactId: presentation.artifact_id as string,
    version: presentation.version as number,
    publishedAt: presentation.published_at as string,
    mode: 'full',
    headline,
    awardSummary,
    commercialImportance,
    fitReason,
    timing,
    recommendedAction,
    targetRoles,
    fitNeedCategories,
    unknowns,
    claims: validClaims,
  }
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

  const presentation = toSignalPresentationView(item.presentation)
  return {
    id: item.signal_id,
    locked: false,
    companyName: item.company.name,
    teaserHeadline: null,
    headline: presentation?.headline ?? null,
    awardSummary: presentation?.awardSummary ?? null,
    commercialImportance: presentation?.commercialImportance ?? null,
    fitReason: presentation?.fitReason ?? null,
    timing: presentation?.timing ?? null,
    recommendedAction: presentation?.recommendedAction ?? null,
    presentationVariant: presentation?.mode === 'full'
      ? 'FULL'
      : presentation?.mode === 'factualFallback'
        ? 'FACTUAL_FALLBACK'
        : null,
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
      eventDateKind: eventDateKind(undefined, _item.event.status),
      eventStatus: _item.event.status,
      awardDate: null,
      presentation: null,
      matchLabel: null,
      matchReasons: [],
      sourceSystem: null,
      whyNow: _item.event.why_now,
    }
  }

  const presentation = toSignalPresentationView(_item.presentation)

  return {
    id: _item.signal_id,
    locked: false,
    companyName: _item.company.name,
    eventTitle: null,
    amount: _item.contract.amount,
    location: _item.contract.location,
    eventDate: _item.event.date,
    eventDateKind: eventDateKind(_item.event.clock, _item.event.status),
    eventStatus: _item.event.status,
    awardDate: _item.contract.dates.award,
    presentation,
    matchLabel: null,
    matchReasons: [],
    sourceSystem: _item.source.system,
    whyNow: '',
  }
}

export function toSignalCards(page: FeedPage): SignalCardView[] {
  return page.items.map(toSignalCard)
}

export function toSignalDetailView(detail: UnlockedDetail): SignalDetailView {
  return {
    id: detail.signal_id,
    companyName: detail.company.name,
    companyKey: detail.company_key ?? null,
    companyCountry: detail.company.country,
    companyIdentifier: detail.company.identifier,
    sourceSystem: detail.source.system,
    presentation: toSignalPresentationView(detail.presentation),
    facts: {
      amount: detail.contract.amount,
      location: detail.contract.location,
      eventDate: detail.event.date,
      eventDateKind: eventDateKind(detail.event.clock, detail.event.status),
      awardDate: detail.contract.dates.award,
      execution: null,
      buyer: detail.contract.buyer?.name ?? null,
      officialTitle: detail.contract.title,
      notice: detail.source.notice_id,
      cpv: detail.contract.cpv,
      sourceUrl: safeHttpsUrl(detail.source.url),
    },
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
