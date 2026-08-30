export type HealthStatus = 'READY' | 'DEGRADED' | 'NOT_READY'
export type GateStatus = 'READY' | 'NOT_READY' | 'INSUFFICIENT_EVIDENCE'
export type AutonomyMode = 'SHADOW' | 'ASSISTED' | 'AUTONOMOUS_CAPPED' | 'ADAPTIVE_SCALE'

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
  h_g_scale: GateEvidence
  highest_safe_mode: AutonomyMode
  blockers: string[]
  evidence_refs: string[]
}

export interface FounderOverview {
  version: 'founder-console-overview-v1'
  environment: 'PRODUCTION'
  read_only: true
  generated_at: string
  today: {
    generated_at: string
    open_attention_count: number
    critical_attention_count: number
    positive_replies_last_completed_week: number
    paid_accounts_last_completed_week: number
    business_period_start: string
    business_period_end: string
    system_status: HealthStatus
    hermes_status: HealthStatus
    highest_safe_mode: AutonomyMode
  }
  attention: AttentionItem[]
  business: CommercialReport
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
