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
  customer_input: TargetIcpInput
  missing_fields: string[]
  created_at: string
  updated_at: string
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
}

export interface SignalEvent {
  status: EventStatus
  type: CustomerEventType | null
  clock: string | null
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
  category: string | null
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
    groups: { plausible_need: string; label: string; items: EvidenceItem[] }[]
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
  target_icp_id: string | null
  company: Company
  event: SignalEvent
  contract: Contract
  analysis: Analysis
  source: SignalSource
}

export interface LockedFeedItem {
  locked: true
  signal_id: string
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
}

export type FeedItem = UnlockedFeedItem | LockedFeedItem

export function isLocked(item: FeedItem | SignalDetail): item is LockedFeedItem | LockedDetail {
  return item.locked === true
}

export interface FeedPage {
  items: FeedItem[]
  total_returned: number
  page: { limit: number; offset: number; has_more: boolean; scan_truncated: boolean }
  excluded: { without_display_name: number; by_freshness: number }
  read_at: string
  freshness: Freshness
  language: string
  plan_code: PlanCode
  policy: { feed: string; recency: string; paywall: string }
}

export type UnlockedDetail = UnlockedFeedItem & {
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
