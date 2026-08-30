import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FounderApp } from './FounderApp'
import type { FounderOverview, FounderSession, GateEvidence } from './types'

const SESSION: FounderSession = {
  version: 'founder-session-v1',
  service: 'kivou-founder-control',
  environment: 'PRODUCTION',
  operator_email: 'rodrigue.bruppacher@gmail.com',
  read_only: true,
  generated_at: '2026-08-29T18:30:00Z',
}

const NOT_READY_GATE: GateEvidence = {
  status: 'NOT_READY',
  reason_codes: ['RUNTIME_OBSERVATION_UNAVAILABLE'],
  evidence_refs: [],
}

const OVERVIEW: FounderOverview = {
  version: 'founder-console-overview-v1',
  environment: 'PRODUCTION',
  read_only: true,
  generated_at: '2026-08-29T18:30:00Z',
  today: {
    generated_at: '2026-08-29T18:30:00Z',
    open_attention_count: 1,
    critical_attention_count: 1,
    positive_replies_last_completed_week: 3,
    paid_accounts_last_completed_week: 1,
    business_period_start: '2026-08-17T22:00:00Z',
    business_period_end: '2026-08-24T22:00:00Z',
    system_status: 'NOT_READY',
    hermes_status: 'NOT_READY',
    highest_safe_mode: 'SHADOW',
  },
  attention: [
    {
      kind: 'INCIDENT',
      item_ref: 'incident-safe-ref',
      severity: 'CRITICAL',
      status: 'OPEN',
      occurred_at: '2026-08-29T18:20:00Z',
      title_code: 'PROVIDER_FAILURE',
      reason_codes: ['PROVIDER_UNAVAILABLE'],
      scope_type: 'GLOBAL',
      scope_ref: 'acquisition',
      source_component: null,
      attempt_count: null,
      human_review_required: true,
      pause_required: true,
    },
  ],
  business: {
    report_version: 'weekly-commercial-cockpit-v1',
    report_ref: 'a'.repeat(64),
    week_start: '2026-08-17T22:00:00Z',
    week_end: '2026-08-24T22:00:00Z',
    captured_at: '2026-08-24T22:00:00Z',
    timezone: 'Europe/Zurich',
    delivery_semantics: 'PROXY_SENT_MINUS_BOUNCE_V1',
    funnel: {
      delivered_proxy_count: 10,
      positive_reply_count: 3,
      click_count: 2,
      activated_account_count: 2,
      paid_account_count: 1,
      mrr_by_currency: [{ currency: 'CHF', minor_units: 9900 }],
      churn_count: 0,
    },
    analytical_rows: [
      {
        country: 'CH',
        sector_ref: 'cybersecurity',
        need_ref: 'specialist_subcontracting',
        campaign_ref: 'campaign-safe-ref',
        delivered_proxy_count: 10,
        positive_reply_count: 3,
        click_count: 2,
        activated_account_count: 2,
        paid_account_count: 1,
        mrr_by_currency: [{ currency: 'CHF', minor_units: 9900 }],
        churn_count: 0,
        positive_reply_rate: '0.300000',
        click_rate: '0.200000',
        activation_rate: '0.200000',
        paid_rate: '0.100000',
      },
    ],
    wedge_m2_efficiency: [],
    data_quality: {
      delivery_is_proxy: true,
      unresolved_sector_count: 0,
      unknown_mrr_journey_count: 0,
      m2_insufficient_wedges: [],
      captured_at: '2026-08-24T22:00:00Z',
    },
  },
  quality: {
    version: 'founder-quality-summary-v1',
    semantics: 'CURRENT_FEEDBACK_UPDATED_IN_WINDOW_V1',
    window_start: '2026-07-30T18:30:00Z',
    window_end: '2026-08-29T18:30:00Z',
    feedback_updated_in_window_count: 2,
    relevant_feedback_updated_in_window_count: 1,
    not_relevant_feedback_updated_in_window_count: 1,
    contacted_in_window_count: 1,
    negative_feedback_rate_bps: 5000,
    negative_reason_counts: [{ reason_code: 'wrong_need', count: 1 }],
    unresolved_sector_count: 0,
    unknown_mrr_journey_count: 0,
  },
  system: {
    health: {
      version: 'acquisition-operational-health-v1',
      observed_at: '2026-08-29T18:30:00Z',
      api: 'READY',
      database: 'READY',
      hermes_runtime: 'NOT_READY',
      supervisor_loop: 'NOT_READY',
      policy_control: 'NOT_READY',
      campaign_execution: 'NOT_READY',
      dlq: 'READY',
      circuit_breakers: 'NOT_READY',
      status: 'NOT_READY',
      reason_codes: ['RUNTIME_OBSERVATION_UNAVAILABLE'],
    },
    readiness: {
      version: 'autonomous-readiness-v1',
      evaluated_at: '2026-08-29T18:30:00Z',
      h_a_runtime: NOT_READY_GATE,
      h_b_state: { status: 'READY', reason_codes: [], evidence_refs: [] },
      h_c_policy: NOT_READY_GATE,
      h_d_shadow: {
        status: 'INSUFFICIENT_EVIDENCE',
        reason_codes: ['HUMAN_REVIEW_TRUTH_UNAVAILABLE'],
        evidence_refs: [],
      },
      h_e_capped: NOT_READY_GATE,
      h_f_closed_loop: { status: 'READY', reason_codes: [], evidence_refs: [] },
      h_g_scale: NOT_READY_GATE,
      highest_safe_mode: 'SHADOW',
      blockers: ['RUNTIME_OBSERVATION_UNAVAILABLE'],
      evidence_refs: [],
    },
    hermes: {
      name: 'Hermes Acquisition Supervisor',
      status: 'NOT_READY',
      highest_safe_mode: 'SHADOW',
      observed_at: '2026-08-29T18:30:00Z',
      reason_codes: ['RUNTIME_OBSERVATION_UNAVAILABLE'],
    },
    database_access: 'READ_ONLY',
  },
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FounderApp', () => {
  it('renders production read models without fake agents or write actions', async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      return {
        ok: true,
        status: 200,
        json: async () => (url.includes('/overview') ? OVERVIEW : SESSION),
      }
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<FounderApp />)

    expect(screen.getByText('Connexion aux read models de production…')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Ce qui mérite ton attention.' })).toBeInTheDocument()
    expect(screen.getByText('rodrigue.bruppacher@gmail.com')).toBeInTheDocument()
    expect(screen.getByText('Provider failure')).toBeInTheDocument()
    expect(screen.getAllByText(/99[.,]00.*CHF/).length).toBeGreaterThan(0)
    expect(screen.getByText('Wrong need')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Hermes Acquisition Supervisor' })).toBeInTheDocument()
    const period = screen.getByRole('combobox', { name: 'Semaine terminée' })
    expect(within(period).getAllByRole('option')).toHaveLength(52)
    expect(screen.queryByRole('button', { name: /approuver|refuser|pause/i })).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/founder/overview?week_offset=0',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })

  it('fails visibly when the founder boundary refuses the request', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
      }),
    )

    render(<FounderApp />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Accès refusé')
    expect(screen.queryByText('Ce qui mérite ton attention.')).not.toBeInTheDocument()
  })
})
