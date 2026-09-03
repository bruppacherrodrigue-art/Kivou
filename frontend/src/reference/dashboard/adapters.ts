import type {
  BillingStatus,
  CardPresentation,
  CompanyProfile,
  EventStatus,
  FeedItem,
  FeedPage,
  SignalFactualDisplay,
  SignalEventClock,
  TargetIcp,
  WinnerEnrichment,
} from '../../api/types'
import type {
  BillingAccessView,
  CompanySummaryView,
  OverviewAwardCardView,
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
const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/
const FACTUAL_DISPLAY_KEYS = new Set([
  'headline',
  'market_summary',
  'object_short',
  'date',
  'completeness',
  'missing_fields',
])
const FACTUAL_DATE_KEYS = new Set(['value', 'kind'])
const FACTUAL_DATE_KINDS = new Set(['award', 'notification', 'publication', 'unknown'])
const FACTUAL_COMPLETENESS = new Set(['verified', 'partial', 'to_verify'])
const WINNER_ENRICHMENT_KEYS = new Set([
  'status',
  'missing_fields',
  'last_verified_at',
  'error_code',
  'source',
])
const WINNER_SOURCE_KEYS = new Set([
  'kind',
  'connector',
  'notice_id',
  'url',
  'retrieved_at',
])
const WINNER_ENRICHMENT_STATUSES = new Set([
  'pending',
  'in_progress',
  'completed',
  'partial',
  'failed',
])

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

function isNullableStrictText(value: unknown, maximum: number): value is string | null {
  return value === null || isStrictText(value, maximum)
}

function isBoundedUniqueTextList(value: unknown): value is string[] {
  return Array.isArray(value)
    && value.length <= 16
    && value.every((entry) => isStrictText(entry, 64))
    && new Set(value).size === value.length
}

export function publishedFactualDisplay(value: unknown): SignalFactualDisplay | null {
  if (
    !isRecord(value)
    || !hasExactKeys(value, FACTUAL_DISPLAY_KEYS)
    || !isRecord(value.date)
    || !hasExactKeys(value.date, FACTUAL_DATE_KEYS)
    || !isStrictText(value.headline, 768)
    || !isNullableStrictText(value.market_summary, 180)
    || !isNullableStrictText(value.object_short, 180)
    || value.market_summary !== value.object_short
    || !(value.date.value === null
      || (typeof value.date.value === 'string' && ISO_DATE_PATTERN.test(value.date.value)))
    || typeof value.date.kind !== 'string'
    || !FACTUAL_DATE_KINDS.has(value.date.kind)
    || typeof value.completeness !== 'string'
    || !FACTUAL_COMPLETENESS.has(value.completeness)
    || !isBoundedUniqueTextList(value.missing_fields)
  ) return null
  return value as unknown as SignalFactualDisplay
}

export function publishedWinnerEnrichment(value: unknown): WinnerEnrichment | null {
  if (
    !isRecord(value)
    || !hasExactKeys(value, WINNER_ENRICHMENT_KEYS)
    || !isRecord(value.source)
    || !hasExactKeys(value.source, WINNER_SOURCE_KEYS)
    || typeof value.status !== 'string'
    || !WINNER_ENRICHMENT_STATUSES.has(value.status)
    || !isBoundedUniqueTextList(value.missing_fields)
    || !(value.last_verified_at === null || isAwareIsoDateTime(value.last_verified_at))
    || !(value.error_code === null || isStrictText(value.error_code, 64))
    || (value.status === 'failed') !== (value.error_code !== null)
    || value.source.kind !== 'public_notice'
    || !isStrictText(value.source.connector, 512)
    || !isStrictText(value.source.notice_id, 512)
    || !(value.source.url === null
      || (isStrictText(value.source.url, 2_048)
        && value.source.url.startsWith('https://')))
    || !(value.source.retrieved_at === null || isAwareIsoDateTime(value.source.retrieved_at))
  ) return null
  return value as unknown as WinnerEnrichment
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
    || !Number.isSafeInteger(value.version)
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

/** « 27920022400012 » → « 279 200 224 00012 ». Les autres schémas restent tels quels. */
export function formatOfficialIdentifier(scheme: string | null, value: string | null): string | null {
  if (!value) return null
  if (scheme === 'SIRET' && /^\d{14}$/.test(value)) {
    return `${value.slice(0, 3)} ${value.slice(3, 6)} ${value.slice(6, 9)} ${value.slice(9)}`
  }
  return value
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

export function toOverviewAwardCard(item: FeedItem): OverviewAwardCardView {
  if (item.locked) {
    const clock = EVENT_CLOCK_BY_STATUS[item.event.status]
    return {
      id: item.signal_id,
      locked: true,
      presentationArtifactId: null,
      companyName: null,
      buyerName: null,
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
      eventDate: item.event.date,
      eventDateKind: eventDateKind(clock, item.event.status),
      sourceSystem: null,
    }
  }

  const presentation = publishedPresentation(item.presentation)
  const content = presentation?.content
  return {
    id: item.signal_id,
    locked: false,
    presentationArtifactId: presentation?.artifact_id ?? null,
    companyName: item.company.name,
    buyerName: item.contract.buyer?.name ?? null,
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
    eventDate: item.event.date,
    eventDateKind: eventDateKind(item.event.clock, item.event.status),
    sourceSystem: item.source.system,
  }
}

export function toOverviewAwardCards(page: FeedPage): OverviewAwardCardView[] {
  return page.items.map(toOverviewAwardCard)
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
