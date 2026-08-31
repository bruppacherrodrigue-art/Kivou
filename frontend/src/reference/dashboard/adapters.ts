import type {
  BillingStatus,
  CardPresentation,
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

const ENVELOPE_KEYS = new Set([
  'artifact_id',
  'version',
  'status',
  'schema_version',
  'published_at',
  'content',
])
const CONTENT_KEYS = new Set([
  'schema_version',
  'variant',
  'headline',
  'award_summary',
  'commercial_importance',
  'fit_reason',
  'timing',
  'recommended_action',
  'target_roles',
  'fit_need_categories',
  'unknowns',
  'claims',
])
const CLAIM_KEYS = new Set(['claim_id', 'kind', 'text', 'evidence_refs', 'confidence'])
const TARGET_ROLE_KEYS = new Set(['role', 'rationale', 'evidence_refs'])
const UNKNOWN_KEYS = new Set(['text', 'evidence_refs'])
const CLAIM_KINDS = new Set(['FACT', 'INFERENCE', 'RECOMMENDATION'])
const CLAIM_CONFIDENCES = new Set(['high', 'medium', 'low'])
const TARGET_ROLE_KINDS = new Set([
  'PROCUREMENT_MANAGER',
  'SITE_PROCUREMENT_MANAGER',
  'PROJECT_MANAGER',
  'WORKS_MANAGER',
  'SUPPLY_MANAGER',
])
const NEED_CATEGORIES = new Set([
  'workforce_capacity',
  'equipment_or_rental',
  'materials_or_components',
  'logistics_and_transport',
  'specialist_subcontracting',
  'safety_and_ppe',
  'waste_and_environment',
])
const ARTIFACT_ID_PATTERN = /^[0-9a-f]{64}$/
const CLAIM_ID_PATTERN = /^[A-Z][A-Z0-9_]{0,63}$/
const AWARE_ISO_DATETIME_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/

type UnknownRecord = Record<string, unknown>

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: UnknownRecord, expected: ReadonlySet<string>): boolean {
  const actual = Object.keys(value)
  return actual.length === expected.size && actual.every((key) => expected.has(key))
}

function isStrictText(value: unknown, maximum: number): value is string {
  return typeof value === 'string'
    && value === value.trim()
    && [...value].length >= 1
    && [...value].length <= maximum
}

function isAwareIsoDateTime(value: unknown): value is string {
  if (typeof value !== 'string' || value !== value.trim()) return false
  const match = AWARE_ISO_DATETIME_PATTERN.exec(value)
  if (!match) return false

  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const hour = Number(match[4])
  const minute = Number(match[5])
  const second = Number(match[6])
  if (
    year < 1
    || month < 1
    || month > 12
    || hour > 23
    || minute > 59
    || second > 59
  ) return false

  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const daysInMonth = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  if (day < 1 || day > daysInMonth[month - 1]) return false

  const zone = match[8]
  if (zone !== 'Z') {
    const offsetHour = Number(zone.slice(1, 3))
    const offsetMinute = Number(zone.slice(4, 6))
    if (offsetHour > 23 || offsetMinute > 59) return false
  }
  return true
}

function hasEvidenceRefs(value: unknown): value is string[] {
  return Array.isArray(value)
    && value.length > 0
    && value.length <= 16
    && value.every((reference) => isStrictText(reference, 256))
}

function isEvidencedClaim(value: unknown): value is UnknownRecord {
  if (!isRecord(value) || !hasExactKeys(value, CLAIM_KEYS)) return false
  if (
    typeof value.claim_id !== 'string'
    || !CLAIM_ID_PATTERN.test(value.claim_id)
    || !isStrictText(value.text, 420)
    || typeof value.kind !== 'string'
    || !CLAIM_KINDS.has(value.kind)
    || !hasEvidenceRefs(value.evidence_refs)
  ) return false
  return value.kind === 'INFERENCE'
    ? typeof value.confidence === 'string' && CLAIM_CONFIDENCES.has(value.confidence)
    : value.confidence === null
}

function isEvidencedUnknown(value: unknown): value is UnknownRecord {
  return isRecord(value)
    && hasExactKeys(value, UNKNOWN_KEYS)
    && isStrictText(value.text, 240)
    && hasEvidenceRefs(value.evidence_refs)
}

function isEvidencedRole(value: unknown): value is UnknownRecord {
  return isRecord(value)
    && hasExactKeys(value, TARGET_ROLE_KEYS)
    && typeof value.role === 'string'
    && TARGET_ROLE_KINDS.has(value.role)
    && isStrictText(value.rationale, 420)
    && hasEvidenceRefs(value.evidence_refs)
}

function hasExactClaim(
  claims: UnknownRecord[],
  text: unknown,
  kind: 'FACT' | 'INFERENCE' | 'RECOMMENDATION',
): boolean {
  return typeof text === 'string'
    && claims.some((claim) => claim.kind === kind && claim.text === text)
}

/**
 * Garde exact du contrat public au point de consommation. PR5 pourra en
 * centraliser l'emplacement et le réemploi ; ici, aucun champ n'est réparé,
 * normalisé ou complété avant rendu.
 */
export function publishedPresentation(value: unknown): CardPresentation | null {
  if (
    !isRecord(value)
    || !hasExactKeys(value, ENVELOPE_KEYS)
    || !isRecord(value.content)
    || !hasExactKeys(value.content, CONTENT_KEYS)
  ) return null
  const content = value.content
  if (
    typeof value.artifact_id !== 'string'
    || !ARTIFACT_ID_PATTERN.test(value.artifact_id)
    || !Number.isInteger(value.version)
    || (value.version as number) < 1
    || !isAwareIsoDateTime(value.published_at)
    || value.schema_version !== 'card-presentation-v1'
    || content.schema_version !== 'card-presentation-v1'
    || !isStrictText(content.headline, 160)
    || !isStrictText(content.award_summary, 420)
    || !(content.commercial_importance === null
      || isStrictText(content.commercial_importance, 420))
    || !(content.fit_reason === null || isStrictText(content.fit_reason, 420))
    || !(content.timing === null || isStrictText(content.timing, 320))
    || !(content.recommended_action === null
      || isStrictText(content.recommended_action, 320))
    || !Array.isArray(content.claims)
    || content.claims.length === 0
    || content.claims.length > 12
    || !content.claims.every(isEvidencedClaim)
    || !Array.isArray(content.unknowns)
    || content.unknowns.length > 8
    || !content.unknowns.every(isEvidencedUnknown)
    || !Array.isArray(content.target_roles)
    || content.target_roles.length > 6
    || !content.target_roles.every(isEvidencedRole)
    || !Array.isArray(content.fit_need_categories)
    || content.fit_need_categories.length > 8
    || !content.fit_need_categories.every(
      (category) => typeof category === 'string' && NEED_CATEGORIES.has(category),
    )
  ) return null

  const claims = content.claims
  const roles = content.target_roles
  const categories = content.fit_need_categories
  if (
    new Set(claims.map((claim) => claim.claim_id)).size !== claims.length
    || new Set(roles.map((role) => role.role)).size !== roles.length
    || new Set(categories).size !== categories.length
    || !hasExactClaim(claims, content.headline, 'FACT')
    || !hasExactClaim(claims, content.award_summary, 'FACT')
  ) return null

  if (value.status === 'FALLBACK' && content.variant === 'FACTUAL_FALLBACK') {
    if (
      content.commercial_importance !== null
      || content.fit_reason !== null
      || content.timing !== null
      || content.recommended_action !== null
      || roles.length !== 0
      || categories.length !== 0
      || !claims.every((claim) => claim.kind === 'FACT')
    ) return null
    return value as unknown as CardPresentation
  }

  if (value.status !== 'PASS' || content.variant !== 'FULL') return null
  if (
    roles.length === 0
    || categories.length === 0
    || !hasExactClaim(claims, content.commercial_importance, 'INFERENCE')
    || !hasExactClaim(claims, content.fit_reason, 'INFERENCE')
    || !hasExactClaim(claims, content.timing, 'INFERENCE')
    || !hasExactClaim(claims, content.recommended_action, 'RECOMMENDATION')
  ) return null
  return value as unknown as CardPresentation
}

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

  const presentation = publishedPresentation(item.presentation)
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
  const presentation = publishedPresentation(detail.presentation)
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
