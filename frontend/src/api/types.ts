/* Le contrat de l'API, en types.
 *
 * Ces types DÉCRIVENT le backend ; ils ne le décident pas. Chacun a été relevé
 * dans `src/signals/api/` et `src/signals/feed/view.py`. Un champ qui n'y
 * figure pas n'a pas sa place ici : le frontend ne doit jamais inventer une
 * donnée que l'API ne renvoie pas.
 */

// ─── Vocabulaire machine (jamais traduit) ────────────────────────────────────

export type Locale = 'fr' | 'en'
export type PlanCode = 'discovery' | 'essential' | 'pro' | 'scale'
export type PurchasablePlan = 'essential' | 'pro' | 'scale'
export type Currency = 'chf' | 'eur'
export type Freshness = 'new' | 'recent_or_aging' | 'all'
export type OnboardingStatus = 'account_created' | 'icp_incomplete' | 'ready_for_signals'
export type AlertCadence = 'none' | 'weekly' | 'daily' | 'priority'
export type FilterLevel = 'minimum' | 'basic' | 'advanced'
export type ExportLevel = 'none' | 'manual' | 'scheduled'
export type TerritoryMode = 'single' | 'multiple' | 'expanded'

/** Le statut unifié d'un signal pour CE compte, produit par
 *  `signals.engagement.status.unified_status`. Le frontend ne le calcule
 *  jamais : il le reçoit et le rend. */
export type UnifiedStatus = 'new' | 'saved' | 'ignored' | 'contacted'

/** Les statuts d'événement produits par `recency`. Le frontend ne les calcule
 *  jamais : il les reçoit et les rend. */
export type EventStatus =
  | 'recent_award'
  | 'recently_notified_contract'
  | 'recently_published_award'
  | 'aging_award'
  | 'stale_award'
  | 'award_date_unknown'
  | 'invalid_award_date'

/** Seuls trois statuts portent un type d'événement client (`customer_event_type`). */
export type CustomerEventType =
  | 'recent_award'
  | 'recently_notified_contract'
  | 'recently_published_award'

/** Horloge qualifiée par le backend pour la date publiée dans `event.date`. */
export type SignalEventClock = 'award' | 'notification' | 'publication'
export type SignalFactualDateKind = SignalEventClock | 'unknown'

/** Taxonomie fermée du Need Graph exposée par le backend. */
export type NeedCategory =
  | 'workforce_capacity'
  | 'equipment_or_rental'
  | 'materials_or_components'
  | 'logistics_and_transport'
  | 'specialist_subcontracting'
  | 'safety_and_ppe'
  | 'waste_and_environment'

export type MagnitudeBand = 'under_50k' | '50k_250k' | '250k_1m' | '1m_5m' | 'over_5m'

export type OfferKind =
  | 'materials_and_components'
  | 'equipment_rental'
  | 'staffing_and_labour'
  | 'transport_and_logistics'
  | 'specialist_subcontracting'
  | 'safety_equipment'
  | 'waste_and_environmental_services'

export const OFFER_KINDS: readonly OfferKind[] = [
  'materials_and_components',
  'equipment_rental',
  'staffing_and_labour',
  'transport_and_logistics',
  'specialist_subcontracting',
  'safety_equipment',
  'waste_and_environmental_services',
] as const

export type BuyerTrade =
  | 'earthworks_and_demolition'
  | 'building_construction'
  | 'roads_and_civil_works'
  | 'rail_infrastructure'
  | 'special_civil_engineering'
  | 'technical_installations'
  | 'interior_finishing'
  | 'equipment_hire'

export const BUYER_TRADES: readonly BuyerTrade[] = [
  'earthworks_and_demolition',
  'building_construction',
  'roads_and_civil_works',
  'rail_infrastructure',
  'special_civil_engineering',
  'technical_installations',
  'interior_finishing',
  'equipment_hire',
] as const

export type Relevance = 'relevant' | 'not_relevant'

export type NegativeReason =
  | 'already_covered'
  | 'done_internally'
  | 'wrong_customer_type'
  | 'too_late'
  | 'wrong_need'
  | 'other'

/** Les six raisons approuvées, dans l'ordre du contrat backend. */
export const NEGATIVE_REASONS: readonly NegativeReason[] = [
  'already_covered',
  'done_internally',
  'wrong_customer_type',
  'too_late',
  'wrong_need',
  'other',
] as const

/** `MAXIMUM_NOTE_LENGTH` de `signals.engagement.schema`. */
export const MAXIMUM_NOTE_LENGTH = 500

/** `MINIMUM_PASSWORD_LENGTH` de `signals.accounts.passwords`. */
export const MINIMUM_PASSWORD_LENGTH = 12

// ─── Compte et session ───────────────────────────────────────────────────────

export interface Me {
  user_id: string
  email: string
  account_id: string
  account_display_name: string
  locale: string
  onboarding_status: OnboardingStatus
  capabilities: {
    commercial_cockpit: boolean
  }
}

// ─── Cockpit commercial interne (SPEC-030) ──────────────────────────────────

export type CockpitCurrency = 'CHF' | 'EUR'

export interface CockpitMoneyTotal {
  currency: CockpitCurrency
  minor_units: number
}

export interface CockpitFunnel {
  delivered_proxy_count: number
  positive_reply_count: number
  click_count: number
  activated_account_count: number
  paid_account_count: number
  mrr_by_currency: CockpitMoneyTotal[]
  churn_count: number
}

export interface CockpitAnalyticalRow extends Omit<CockpitFunnel, 'mrr_by_currency'> {
  country: 'CH' | 'FR'
  sector_ref: string
  need_ref: string
  campaign_ref: string
  mrr_by_currency: CockpitMoneyTotal[]
  positive_reply_rate: string | null
  click_rate: string | null
  activation_rate: string | null
  paid_rate: string | null
}

export interface CockpitWedgeM2 {
  wedge: string
  currency: CockpitCurrency | null
  m2_eligible_delivered_proxy_count: number
  retained_m2_accounts: number
  retained_m2_mrr_minor_units: number | null
  retained_m2_mrr_per_1000_delivered: string | null
  data_status: 'READY' | 'INSUFFICIENT_M2_EVIDENCE'
}

export interface WeeklyCommercialCockpit {
  report_version: 'weekly-commercial-cockpit-v1'
  report_ref: string
  week_start: string
  week_end: string
  captured_at: string
  timezone: 'Europe/Zurich'
  delivery_semantics: 'PROXY_SENT_MINUS_BOUNCE_V1'
  funnel: CockpitFunnel
  analytical_rows: CockpitAnalyticalRow[]
  wedge_m2_efficiency: CockpitWedgeM2[]
  data_quality: {
    delivery_is_proxy: true
    unresolved_sector_count: number
    unknown_mrr_journey_count: number
    matching_disagreement: number
    m2_insufficient_wedges: string[]
    captured_at: string
  }
}

// ─── Profil de ciblage ───────────────────────────────────────────────────────

export interface MonetaryThreshold {
  currency: string
  minimum_amount: number
  maximum_amount: number | null
}

export interface TargetIcpInput {
  offer_summary: string
  offers: OfferKind[]
  secondary_offers: OfferKind[]
  buyer_trades: BuyerTrade[]
  secondary_buyer_trades: BuyerTrade[]
  territories: string[]
  territory_subdivisions?: string[]
  sector_cpv_prefixes?: string[]
  minimum_contract_value: MonetaryThreshold | null
}

export interface TargetIcp {
  target_icp_id: string
  label: string
  status: string
  matching_revision: number
  plan_limit: {
    code: string
    limit: number
    territory_count: number
  } | null
  provisional?: boolean
  customer_input: TargetIcpInput
  missing_fields: string[]
  created_at: string
  updated_at: string
}

export interface TargetIcpOptions {
  zones: { code: string; label: string; country: string }[]
  sectors: { prefix: string; label: string }[]
}

// ─── Signal ──────────────────────────────────────────────────────────────────

export interface Identifier {
  scheme: string | null
  value: string | null
}

export interface Company {
  name: string | null
  country: string | null
  identifier: Identifier | null
  /** Présent seulement quand l'attributaire est un groupement identifié. */
  consortium?: boolean
}

export interface Buyer {
  name: string | null
  country: string | null
  identifier: Identifier | null
}

export interface Money {
  value: string
  currency: string
}

export interface Place {
  country: string | null
  locality: string | null
  postal_code: string | null
  subdivision_code: string | null
  subdivision_label: string | null
}

export interface SignalEvent {
  status: EventStatus
  type: CustomerEventType | null
  clock: SignalEventClock
  date: string | null
  age_days: number | null
  /** Phrase produite par `recency.claim` — la seule autorité sur ce que Kivou
   *  a le droit d'affirmer d'une date. Jamais reformulée côté frontend. */
  headline: string
  why_now: string
  award_date_note: string
  award_clock_status: string
  is_new_opportunity: boolean
}

export interface SignalFactualDisplay {
  headline: string
  market_summary: string | null
  object_short: string | null
  date: {
    value: string | null
    kind: SignalFactualDateKind
  }
  completeness: 'verified' | 'partial' | 'to_verify'
  missing_fields: string[]
}

export interface WinnerEnrichmentSource {
  kind: 'public_notice' | 'official_register'
  connector: string
  notice_id: string
  url: string | null
  retrieved_at: string | null
}

export interface WinnerEnrichment {
  status: 'pending' | 'in_progress' | 'completed' | 'partial' | 'failed'
  official_name?: string | null
  missing_fields: string[]
  last_verified_at: string | null
  error_code: string | null
  source: WinnerEnrichmentSource
}

export type CardPresentationClaimKind = 'FACT' | 'INFERENCE' | 'RECOMMENDATION'
export type CardPresentationConfidence = 'high' | 'medium' | 'low'
export type CardPresentationTargetRoleKind =
  | 'PROCUREMENT_MANAGER'
  | 'SITE_PROCUREMENT_MANAGER'
  | 'PROJECT_MANAGER'
  | 'WORKS_MANAGER'
  | 'SUPPLY_MANAGER'

interface CardPresentationClaimBase {
  claim_id: string
  text: string
  evidence_refs: [string, ...string[]]
}

export type CardPresentationFactClaim = CardPresentationClaimBase & {
  kind: 'FACT'
  confidence: null
}

export type CardPresentationInferenceClaim = CardPresentationClaimBase & {
  kind: 'INFERENCE'
  confidence: CardPresentationConfidence
}

export type CardPresentationRecommendationClaim = CardPresentationClaimBase & {
  kind: 'RECOMMENDATION'
  confidence: null
}

export type CardPresentationClaim =
  | CardPresentationFactClaim
  | CardPresentationInferenceClaim
  | CardPresentationRecommendationClaim

export interface CardPresentationTargetRole {
  role: CardPresentationTargetRoleKind
  rationale: string
  evidence_refs: [string, ...string[]]
}

export interface CardPresentationUnknown {
  text: string
  evidence_refs: [string, ...string[]]
}

interface CardPresentationContentBase {
  schema_version: 'card-presentation-v1'
  headline: string
  award_summary: string
  unknowns: CardPresentationUnknown[]
}

export interface FullCardPresentationContent extends CardPresentationContentBase {
  variant: 'FULL'
  commercial_importance: string
  fit_reason: string
  timing: string
  recommended_action: string
  target_roles: [CardPresentationTargetRole, ...CardPresentationTargetRole[]]
  fit_need_categories: [NeedCategory, ...NeedCategory[]]
  claims: [CardPresentationClaim, ...CardPresentationClaim[]]
}

export interface FactualFallbackCardPresentationContent extends CardPresentationContentBase {
  variant: 'FACTUAL_FALLBACK'
  commercial_importance: null
  fit_reason: null
  timing: null
  recommended_action: null
  target_roles: []
  fit_need_categories: []
  claims: [CardPresentationFactClaim, ...CardPresentationFactClaim[]]
}

interface CardPresentationEnvelopeBase {
  artifact_id: string
  version: number
  schema_version: 'card-presentation-v1'
  published_at: string
}

/**
 * Enveloppe publique exacte de PR1. Le couple statut/variante est discriminé
 * afin qu'un PASS/FALLBACK incohérent ne puisse pas être consommé comme typé.
 */
export type CardPresentation =
  | (CardPresentationEnvelopeBase & {
      status: 'PASS'
      content: FullCardPresentationContent
    })
  | (CardPresentationEnvelopeBase & {
      status: 'FALLBACK'
      content: FactualFallbackCardPresentationContent
    })

export interface Contract {
  title: string | null
  lot: string | null
  lot_title: string | null
  reference: string | null
  buyer: Buyer | null
  amount: Money | null
  cpv: string | null
  location: Place | null
  dates: {
    award: string | null
    contract_notification: string | null
    publication: string | null
  }
}

export interface SignalSource {
  system: string | null
  country: string | null
  notice_id: string | null
  procedure_id: string | null
  url: string | null
}

export interface PlausibleNeed {
  category: NeedCategory | null
  label: string | null
  statement: string | null
  confidence: string | null
  timing: string | null
  timing_label: string | null
  targeted_by_your_profile: boolean
  /** Présent seulement sur le détail (`full=True`). */
  reasoning?: string | null
}

export interface Fit {
  label: string
  target_icp_id: string | null
  target_icp_label: string | null
  reasons: string[]
  for_you_sentence?: string | null
  band?: 'strong' | 'promising' | 'weak' | 'unknown'
}

export interface Analysis {
  plausible_needs: { note: string; items: PlausibleNeed[] }
  fit: Fit
  /** Détail uniquement. */
  contract_reading?: {
    note: string
    summary: string | null
    contract_type: string | null
    sector: string | null
  }
}

export interface EvidenceItem {
  source_system: string | null
  source_kind: string | null
  notice_id: string | null
  procedure_id: string | null
  url: string | null
  path: string | null
  excerpt: string | null
  retrieved_at: string | null
}

export interface Evidence {
  public_facts: { fact: string; label: string; items: EvidenceItem[] }[]
  analysis_inputs: {
    note: string
    groups: { plausible_need: NeedCategory; label: string; items: EvidenceItem[] }[]
  }
}

export interface Interaction {
  relevance: Relevance | null
  reason: NegativeReason | null
  note: string | null
  contacted: boolean
  contacted_at: string | null
  updated_at: string
}

export interface UnlockedFeedItem {
  locked: false
  signal_id: string
  /** Le statut unifié de CE signal pour CE compte. Jamais recalculé côté
   *  frontend. */
  status: UnifiedStatus
  company_key?: string | null
  target_icp_id: string | null
  company: Company
  factual_display: SignalFactualDisplay
  winner_enrichment: WinnerEnrichment
  event: SignalEvent
  contract: Contract
  analysis: Analysis
  source: SignalSource
  presentation: CardPresentation | null
}

export interface LockedFeedItem {
  locked: true
  signal_id: string
  status: UnifiedStatus
  target_icp_id: string | null
  unlock_required: 'paid_plan'
  event: {
    status: EventStatus
    type: CustomerEventType | null
    date: string | null
    why_now: string
    is_new_opportunity: boolean
  }
  context: {
    country: string | null
    place_country: string | null
    sector: string | null
    contract_magnitude: MagnitudeBand | null
    currency: string | null
    plausible_need_count: number
  }
  headline: string
  /** La surface verrouillée de PR1 interdit cette clé, même à `null`. */
  presentation?: never
  factual_display?: never
  winner_enrichment?: never
  company_key?: never
}

export type FeedItem = UnlockedFeedItem | LockedFeedItem

export function isLocked(item: FeedItem | SignalDetail): item is LockedFeedItem | LockedDetail {
  return item.locked === true
}

export interface FeedPage {
  items: FeedItem[]
  total_returned: number
  page: {
    limit: number
    offset: number
    cursor?: string | null
    next_cursor?: string | null
    has_more: boolean
    scan_truncated: boolean
  }
  excluded: {
    without_display_name: number
    by_freshness: number
    by_filters: number
    by_status: number
  }
  /** Comptage par statut unifié, calculé sur l'ensemble filtré — pas
   *  seulement la page courante. */
  counts: Record<UnifiedStatus, number>
  /** `true` si le comptage s'est arrêté avant d'avoir tout scanné : les
   *  chiffres sont un plancher, pas un total. */
  counts_truncated: boolean
  /** `false` dit pourquoi les compteurs sont absents : un client qui affiche
   *  le badge doit vérifier ce champ avant de faire confiance à `counts`. */
  counts_available: boolean
  read_at: string
  freshness: Freshness
  language: string
  plan_code: PlanCode
  provisional_profile?: boolean
  view: 'recent' | 'history'
  history_access: {
    scope: 'grants_only' | 'window' | 'all_available'
    history_days: number | null
  }
  filter_access: {
    date_range: boolean
    country: boolean
    subdivision: boolean
    status: boolean
    sector: boolean
  }
  policy: { feed: string; recency: string; paywall: string }
}

export type UnlockedDetail = UnlockedFeedItem & {
  company_key?: string | null
  evidence: Evidence
  opportunity_id: string
  customer_ready: boolean
  read_at: string
  language: string
  interaction: Interaction | null
}

export type LockedDetail = LockedFeedItem & {
  access: { granted: false; reason: string; upgrade_to: PurchasablePlan[] }
  read_at: string
  language: string
}

export type SignalDetail = UnlockedDetail | LockedDetail

export interface SignalNote {
  signal_id: string
  note: string | null
  updated_at: string | null
}

// ─── Fiche entreprise SaaS ──────────────────────────────────────────────────

export interface CompanyOfficialIdentifier {
  scheme: string
  value: string
}

export interface CompanyOfficialIdentity {
  name: string
  country: string | null
  address: string | null
  identifiers: CompanyOfficialIdentifier[]
  website_url: string | null
  observed_at: string
  source: 'public_notice'
}

export interface CompanyRelatedSignal {
  signal_id: string
  contract_title: string | null
  amount: Money | null
  event: {
    status: EventStatus
    date: string | null
    headline: string
    why_now: string
    award_date_note: string | null
  }
  plausible_needs: {
    label: string
    statement: string | null
    timing_label: string | null
    reasoning: string | null
  }[]
  fit: {
    label: string
    reasons: string[]
    for_you_sentence?: string | null
  }
}

export interface CompanyProfile {
  company_key: string
  city: string | null
  official_identity: CompanyOfficialIdentity
  related_signals: CompanyRelatedSignal[]
  coverage: {
    related_signals_complete: boolean
    unavailable_fields: string[]
  }
  contact_status: CompanyContactStatus
  contacted_at: string | null
  history: Array<{
    type: 'contacted' | 'replied' | 'to_contact' | 'note' | 'signal_saved' | 'signal_contacted'
    occurred_at: string
    signal_key: string | null
  }>
  note: string | null
  signals: UnlockedFeedItem[]
}

export type CompanyContactStatus = 'to_contact' | 'contacted' | 'replied'

export interface CompanyListItem {
  company_key: string
  name: string
  city: string | null
  country: string | null
  awards_count: number
  total_amount: { currency: string; value: string }[]
  last_award_at: string | null
  contact_status: CompanyContactStatus
  contacted_at: string | null
  top_fit: string | null
}

export interface CompanyListPage {
  items: CompanyListItem[]
  page: {
    limit: number
    cursor: string | null
    next_cursor: string | null
    has_more: boolean
    scan_truncated: boolean
  }
  read_at: string
  plan_code: string
}

export interface CompanyContactResult {
  company_key: string
  contact_status: CompanyContactStatus
  contacted_at: string | null
  updated_at: string
}

export interface CompanyNoteResult {
  company_key: string
  note: string | null
  updated_at: string
}

export interface DashboardFollowUp {
  company_key: string
  name: string
  last_signal: UnlockedFeedItem
  days_since_contact: number
}

export interface DashboardResponse {
  as_of: string
  last_seen_at: string | null
  new_since_last_visit: number
  strong_matches: number
  top3: UnlockedFeedItem[]
  to_follow_up: DashboardFollowUp[]
  to_follow_up_truncated: boolean
  week: { new: number; saved: number; contacted: number; replied: number }
  scan_truncated: boolean
  profile: { name: string; sector_label: string; zone_labels: string[] }
  plan: { name: string; opened: number; quota: number | null; period_end: string | null }
}

// ─── Facturation ─────────────────────────────────────────────────────────────

export interface Entitlements {
  max_active_icps: number
  history_days: number | null
  history_scope: 'all_available' | 'window'
  territory_mode: TerritoryMode
  max_territories_per_icp: number | null
  feed_access: boolean
  detail_access: boolean
  evidence_access: boolean
  filter_level: FilterLevel
  export_level: ExportLevel
  alert_cadence: AlertCadence
  granted_signals: number
}

export interface PlanPrice {
  amount_minor_units: number
  currency: string
}

export interface CataloguePlan {
  plan_code: PlanCode
  purchasable: boolean
  recommended: boolean
  monthly_price: Partial<Record<Currency, PlanPrice>>
  entitlements: Entitlements
}

export interface PlanCatalogue {
  catalogue_version: string
  billing_interval: 'month'
  currencies: Currency[]
  plans: CataloguePlan[]
}

/* P0-03A — l'action de facturation SÛRE, décidée par le serveur.
 *
 * Deux questions, deux champs, et les confondre coûte de l'argent réel :
 *
 *     plan_code       →  quels droits le compte a-t-il MAINTENANT ?
 *     billing_action  →  quelle action de facturation est SÛRE maintenant ?
 *
 * Un compte `past_due` vaut `discovery` comme un compte qui n'a jamais payé —
 * mais il porte un abonnement facturé, et lui proposer un paiement le
 * facturerait deux fois. Le frontend ne rejoue donc JAMAIS la règle : il ne
 * connaît ni `TERMINAL_STATUSES`, ni `PAYING_STATUSES`, ni
 * `is_open_subscription()`, et ne déduit rien de `subscription_status`.
 */
export type BillingAction =
  | 'choose_plan'
  | 'manage_subscription'
  | 'recover_payment'
  | 'contact_support'

export interface BillingStatus {
  plan_code: PlanCode
  offer_code: string | null
  currency: string | null
  subscription_status: string | null
  cancel_at_period_end: boolean
  current_period_end: string | null
  /** P0-03G — QUAND l'abonnement s'arrêtera, décidé par le serveur.
   *
   * `null` s'il n'y a aucune résiliation programmée. Le navigateur ne calcule
   * jamais cette date et ne la déduit jamais de `current_period_end` : Stripe
   * permet de planifier une résiliation à une autre date que la fin de période.
   */
  scheduled_cancellation_at: string | null
  payment_issue: string | null
  /** La SEULE autorité sur ce que l'écran de facturation propose. */
  billing_action: BillingAction
  entitlements: Entitlements
  discovery: { granted_signal_count: number; remaining_slots: number; limit: number }
  target_icps_over_limit: string[]
  policy: { billing: string }
}

export interface CheckoutSession {
  checkout_url: string
  plan: PurchasablePlan
  currency: Currency
}

// ─── Notifications ───────────────────────────────────────────────────────────

export interface NotificationPreference {
  email_enabled: boolean
  notification_email: string | null
  updated_at: string
}
