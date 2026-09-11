export type HealthStatus = 'READY' | 'DEGRADED' | 'NOT_READY'
export type GateStatus = 'READY' | 'NOT_READY' | 'INSUFFICIENT_EVIDENCE'
export type AutonomyMode = 'SHADOW' | 'ASSISTED' | 'AUTONOMOUS_CAPPED' | 'ADAPTIVE_VOLUME'
export type FounderTunnelPeriod = 'today' | 'last_7_days'

export interface FounderAcquisitionStatus {
  mode: string | null
  activity: 'RUNNING' | 'STOPPED' | 'UNKNOWN'
  activity_since: string | null
  last_cycle_ref: string | null
  last_cycle_at: string | null
  last_cycle_status: string | null
  last_cycle_reason_code: string | null
}

export interface FounderSession {
  version: 'founder-session-v1'
  service: 'kivou-founder-control'
  environment: 'PRODUCTION'
  operator_email: string
  read_only: true
  generated_at: string
}

export interface MoneyTotal {
  currency: 'CHF' | 'EUR'
  minor_units: number
}

export interface FounderTunnelCounts {
  sent_count: number
  opened_count: number
  click_count: number
  landing_count: number
  confirmed_profile_count: number
  paid_count: number
}

export interface FounderTunnelSlice extends FounderTunnelCounts {
  start_at: string
  end_at: string
}

export interface FounderTunnelCurrent {
  observed_at: string
  mrr_by_currency: MoneyTotal[]
  churn_count: number
}

export interface FounderCommercialTunnel {
  period_kind: FounderTunnelPeriod
  period: FounderTunnelSlice
  cohort_week_offset: number
  cohort: FounderTunnelSlice
  current: FounderTunnelCurrent
}

export interface CommercialFunnel {
  delivered_proxy_count: number
  positive_reply_count: number
  click_count: number
  activated_account_count: number
  paid_account_count: number
  mrr_by_currency: MoneyTotal[]
  churn_count: number
}

export interface CommercialRow extends Omit<CommercialFunnel, 'mrr_by_currency'> {
  country: 'CH' | 'FR'
  sector_ref: string
  need_ref: string
  campaign_ref: string
  mrr_by_currency: MoneyTotal[]
  positive_reply_rate: string | null
  click_rate: string | null
  activation_rate: string | null
  paid_rate: string | null
}

export interface WedgeEfficiency {
  wedge: string
  currency: 'CHF' | 'EUR' | null
  m2_eligible_delivered_proxy_count: number
  retained_m2_accounts: number
  retained_m2_mrr_minor_units: number | null
  retained_m2_mrr_per_1000_delivered: string | null
  data_status: 'READY' | 'INSUFFICIENT_M2_EVIDENCE'
}

export interface CommercialReport {
  report_version: 'weekly-commercial-cockpit-v1'
  report_ref: string
  week_start: string
  week_end: string
  captured_at: string
  timezone: 'Europe/Zurich'
  delivery_semantics: 'PROXY_SENT_MINUS_BOUNCE_V1'
  funnel: CommercialFunnel
  analytical_rows: CommercialRow[]
  wedge_m2_efficiency: WedgeEfficiency[]
  data_quality: {
    delivery_is_proxy: true
    unresolved_sector_count: number
    unknown_mrr_journey_count: number
    m2_insufficient_wedges: string[]
    captured_at: string
  }
}

export interface AttentionItem {
  kind: 'INCIDENT' | 'DEAD_LETTER'
  item_ref: string
  severity: 'WARNING' | 'HIGH' | 'CRITICAL'
  status: string
  occurred_at: string
  title_code: string
  reason_codes: string[]
  scope_type: string
  scope_ref: string
  source_component: string | null
  attempt_count: number | null
  human_review_required: boolean
  pause_required: boolean
}

export interface QualitySummary {
  version: 'founder-quality-summary-v1'
  semantics: 'CURRENT_FEEDBACK_UPDATED_IN_WINDOW_V1'
  window_start: string
  window_end: string
  feedback_updated_in_window_count: number
  relevant_feedback_updated_in_window_count: number
  not_relevant_feedback_updated_in_window_count: number
  contacted_in_window_count: number
  negative_feedback_rate_bps: number | null
  negative_reason_counts: Array<{ reason_code: string; count: number }>
  unresolved_sector_count: number
  unknown_mrr_journey_count: number
}

export interface OperationalHealth {
  version: string
  observed_at: string
  api: HealthStatus
  database: HealthStatus
  hermes_runtime: HealthStatus
  supervisor_loop: HealthStatus
  policy_control: HealthStatus
  campaign_execution: HealthStatus
  dlq: HealthStatus
  circuit_breakers: HealthStatus
  status: HealthStatus
  reason_codes: string[]
}

export interface GateEvidence {
  status: GateStatus
  reason_codes: string[]
  evidence_refs: string[]
}

export interface AutonomousReadiness {
  version: string
  evaluated_at: string
  h_a_runtime: GateEvidence
  h_b_state: GateEvidence
  h_c_policy: GateEvidence
  h_d_shadow: GateEvidence
  h_e_capped: GateEvidence
  h_f_closed_loop: GateEvidence
  h_g_precision: GateEvidence
  highest_safe_mode: AutonomyMode
  blockers: string[]
  evidence_refs: string[]
}

export interface FounderOverview {
  version: 'founder-console-overview-v1'
  environment: 'PRODUCTION'
  read_only: true
  generated_at: string
  acquisition_status: FounderAcquisitionStatus
  today: {
    generated_at: string
    open_attention_count: number
    critical_attention_count: number
    positive_replies_last_completed_week: number
    paid_accounts_last_completed_week: number
    business_period_start: string
    business_period_end: string
  }
  attention: AttentionItem[]
  business: CommercialReport
  commercial_tunnel: FounderCommercialTunnel
  quality: QualitySummary
  system: {
    health: OperationalHealth
    readiness: AutonomousReadiness
    hermes: {
      name: 'Hermes Acquisition Supervisor'
      status: HealthStatus
      highest_safe_mode: AutonomyMode
      observed_at: string
      reason_codes: string[]
    }
    database_access: 'READ_ONLY'
  }
}

export type FounderDirectoryStatus =
  | 'confirmed_domain'
  | 'without_website'
  | 'reverification_required'

export type FounderDirectoryQualificationStatus =
  | FounderDirectoryStatus
  | 'to_qualify'

export interface FounderProspectionFilters {
  page: number
  q: string
  family: string
  department: string
  status: FounderDirectoryStatus | ''
}

export interface FounderProspection {
  version: 'founder-prospection-v1'
  generated_at: string
  read_only: true
  acquisition_status: FounderAcquisitionStatus
  queue: {
    available: boolean
    last_cycle_at: string | null
    items: FounderProspectionQueueItem[]
  }
  directory: {
    summary: {
      company_count: number
      confirmed_domain_count: number
      verified_email_count: number
      reverification_required_count: number
    }
    family_counts: FounderCountFacet[]
    department_counts: FounderCountFacet[]
    rows: FounderDirectoryRow[]
    pagination: {
      page: number
      page_size: number
      total_items: number
      total_pages: number
    }
  }
  targeting: FounderTargetingCycle | null
  results: {
    sent_count: number
    opened_count: number
    attribution_click_count: number
    landing_count: number
    confirmed_profile_count: number
    paid_account_count: number
    mrr_by_currency: MoneyTotal[]
    no_sends_yet: boolean
  }
}

export interface FounderCountFacet {
  key: string
  label: string
  count: number
}

export interface FounderDirectoryRow {
  siren: string
  legal_name: string
  family_keys: string[]
  department: string | null
  department_name: string | null
  city: string | null
  employees: number | null
  domain: string | null
  website_url: string | null
  confirmed_domain: boolean
  qualification_status: FounderDirectoryQualificationStatus
  professional_email: string | null
  email_source: string | null
  email_verification_status: string | null
  email_contact_name: string | null
  email_contact_title: string | null
  reverification_required_at: string | null
  reverification_reason: string | null
  updated_at: string
}

export interface FounderProspectionQueueItem {
  target_ref: string
  status: 'pending_review'
  company_name: string
  city: string | null
  employees: number | null
  family_key: string
  director_name: string | null
  director_title: string | null
  email_address: string
  email_source: 'apollo' | 'site' | 'manual'
  email_verification_status: string
  bait_holder: string
  bait_subject: string
  bait_amount_minor_units: number | null
  bait_currency: string | null
  mail_subject: string
  mail_body: string
  mail_html: string
}

export interface FounderTargetingCycle {
  cycle_ref: string
  status: string
  started_at: string
  updated_at: string
  completed_at: string | null
  recent: boolean
  signal: {
    title: string | null
    amount_minor_units: number | null
    currency: string | null
  }
  family_keys: string[]
  sirene_account_count: number
  confirmed_domain_count: number
  email_counts_by_level: Array<{ level: number; count: number }>
  deviation_counts: Array<{ reason_code: string; count: number }>
}
