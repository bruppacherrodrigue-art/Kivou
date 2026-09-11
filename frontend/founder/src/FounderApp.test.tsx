import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
  acquisition_status: {
    mode: 'SHADOW',
    activity: 'STOPPED',
    activity_since: '2026-08-29T16:00:00Z',
    last_cycle_ref: 'cycle-safe-ref',
    last_cycle_at: '2026-08-29T15:45:00Z',
    last_cycle_status: 'SUPPRESSED',
    last_cycle_reason_code: 'NO_ELIGIBLE_OPPORTUNITY',
  },
  today: {
    generated_at: '2026-08-29T18:30:00Z',
    open_attention_count: 1,
    critical_attention_count: 1,
    positive_replies_last_completed_week: 3,
    paid_accounts_last_completed_week: 1,
    business_period_start: '2026-08-17T22:00:00Z',
    business_period_end: '2026-08-24T22:00:00Z',
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
  commercial_tunnel: {
    period_kind: 'last_7_days',
    period: {
      start_at: '2026-08-23T22:00:00Z',
      end_at: '2026-08-29T18:30:00Z',
      sent_count: 11,
      opened_count: 8,
      click_count: 6,
      landing_count: 5,
      confirmed_profile_count: 4,
      paid_count: 3,
    },
    cohort_week_offset: 0,
    cohort: {
      start_at: '2026-08-17T22:00:00Z',
      end_at: '2026-08-24T22:00:00Z',
      sent_count: 21,
      opened_count: 16,
      click_count: 12,
      landing_count: 9,
      confirmed_profile_count: 7,
      paid_count: 5,
    },
    current: {
      observed_at: '2026-08-29T18:30:00Z',
      mrr_by_currency: [
        { currency: 'CHF', minor_units: 12345 },
        { currency: 'EUR', minor_units: 6700 },
      ],
      churn_count: 2,
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
      h_g_precision: NOT_READY_GATE,
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

function overviewFor(url: string): FounderOverview {
  const query = new URL(url, 'https://control.kivou.eu')
  const periodKind = query.searchParams.get('period') === 'today' ? 'today' : 'last_7_days'
  const cohortWeekOffset = Number(query.searchParams.get('week_offset') ?? 0)
  return {
    ...OVERVIEW,
    commercial_tunnel: {
      ...OVERVIEW.commercial_tunnel,
      period_kind: periodKind,
      period: periodKind === 'today'
        ? {
            start_at: '2026-08-28T22:00:00Z',
            end_at: '2026-08-29T18:30:00Z',
            sent_count: 2,
            opened_count: 1,
            click_count: 1,
            landing_count: 1,
            confirmed_profile_count: 1,
            paid_count: 0,
          }
        : OVERVIEW.commercial_tunnel.period,
      cohort_week_offset: cohortWeekOffset,
      cohort: {
        ...OVERVIEW.commercial_tunnel.cohort,
        sent_count: 21 + cohortWeekOffset,
      },
    },
  }
}

function installSuccessfulFetch() {
  const fetchMock = vi.fn(async (input: string | URL | Request) => {
    const url = String(input)
    return {
      ok: true,
      status: 200,
      json: async () => (url.includes('/overview') ? overviewFor(url) : SESSION),
    }
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  window.history.replaceState({}, '', '/')
  vi.unstubAllGlobals()
})

describe('FounderApp', () => {
  it('keeps the three-route navigation available below the tablet breakpoint', () => {
    const styles = readFileSync(resolve(process.cwd(), 'founder/src/styles.css'), 'utf8')

    expect(styles).not.toContain('.control-sidebar nav { display: none; }')
    expect(styles).toContain('@media (max-width: 900px)')
  })

  it('renders production read models without fake agents or write actions', async () => {
    const fetchMock = installSuccessfulFetch()

    render(<FounderApp />)

    expect(screen.getByText('Connexion aux read models de production…')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Aujourd’hui', level: 1 })).toBeInTheDocument()
    expect(screen.getByText('rodrigue.bruppacher@gmail.com')).toBeInTheDocument()
    expect(screen.getByText('Provider failure')).toBeInTheDocument()
    expect(screen.getByText(/123[.,]45.*CHF/)).toBeInTheDocument()
    expect(screen.getByText('Wrong need')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /approuver|refuser|pause/i })).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/founder/overview?week_offset=0&period=last_7_days',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })

  it('affiche la source acquisition unique sur Aujourd’hui et Système', async () => {
    installSuccessfulFetch()

    render(<FounderApp />)

    await screen.findByRole('heading', { name: 'Aujourd’hui', level: 1 })
    const statuses = screen.getAllByLabelText('État de l’acquisition')
    expect(statuses).toHaveLength(2)
    statuses.forEach((status) => {
      expect(within(status).getByText('Mode observation')).toBeInTheDocument()
      expect(within(status).getByText(/Arrêté depuis le/)).toBeInTheDocument()
      expect(within(status).getByText(/cycle-safe-ref/)).toBeInTheDocument()
    })
    expect(statuses[1]).toHaveClass('control-runtime--compact')
    expect(screen.queryByText('État global')).not.toBeInTheDocument()
    expect(screen.queryByText('Hermes')).not.toBeInTheDocument()
    expect(screen.queryByText('Mode sûr actuel')).not.toBeInTheDocument()
    expect(screen.queryByText('Runtime Hermes')).not.toBeInTheDocument()
    expect(screen.getByText('Dead-letter queue')).toBeInTheDocument()
    expect(screen.getByText('État durable')).toBeInTheDocument()
  })

  it('ouvre sur 7 jours et permet période, aujourd’hui et cohorte', async () => {
    const user = userEvent.setup()
    const fetchMock = installSuccessfulFetch()

    render(<FounderApp />)

    const heading = await screen.findByRole('heading', { name: 'Tunnel commercial' })
    const tunnel = heading.closest('section')
    expect(tunnel).not.toBeNull()
    expect(screen.getByRole('tab', { name: 'Période' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('button', { name: '7 derniers jours' })).toHaveAttribute('aria-pressed', 'true')
    const periodPanel = screen.getByRole('tabpanel', { name: 'Période' })
    expect(within(periodPanel).getByText('Envoyés')).toBeInTheDocument()
    expect(within(periodPanel).getByText('Ouverts')).toBeInTheDocument()
    expect(within(periodPanel).getByText('Clics')).toBeInTheDocument()
    expect(within(periodPanel).getByText('Atterrissages')).toBeInTheDocument()
    expect(within(periodPanel).getByText('Profils confirmés')).toBeInTheDocument()
    expect(within(periodPanel).getByText('Payants')).toBeInTheDocument()
    expect(within(periodPanel).getByText('Envoyés').closest('article')).toHaveTextContent('11')
    expect(within(periodPanel).queryByText('MRR')).not.toBeInTheDocument()
    expect(within(periodPanel).queryByText('Churn')).not.toBeInTheDocument()

    const current = screen.getByRole('heading', { name: 'Situation actuelle' }).closest('article')
    expect(current).not.toBeNull()
    expect(within(current!).getByText('MRR')).toBeInTheDocument()
    expect(within(current!).getByText('Churn')).toBeInTheDocument()
    expect(within(current!).getByText(/123[.,]45.*CHF/)).toBeInTheDocument()
    expect(within(current!).getByText('2')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Aujourd’hui' }))
    expect(screen.getByRole('button', { name: 'Aujourd’hui' })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/founder/overview?week_offset=0&period=today',
        expect.objectContaining({ credentials: 'same-origin' }),
      )
    })
    expect(within(screen.getByRole('tabpanel', { name: 'Période' })).getByText('Envoyés').closest('article')).toHaveTextContent('2')

    await user.click(screen.getByRole('tab', { name: 'Par cohorte' }))
    expect(screen.getByRole('tab', { name: 'Par cohorte' })).toHaveAttribute('aria-selected', 'true')
    const cohortPanel = screen.getByRole('tabpanel', { name: 'Par cohorte' })
    expect(within(cohortPanel).getByText(/Cohorte envoyée/)).toBeInTheDocument()
    expect(within(cohortPanel).getByText(/Étapes atteintes depuis/)).toBeInTheDocument()
    const cohortWeek = within(cohortPanel).getByRole('combobox', { name: 'Semaine terminée' })
    expect(within(cohortWeek).getAllByRole('option')).toHaveLength(52)
    await user.selectOptions(cohortWeek, '1')
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/founder/overview?week_offset=1&period=today',
        expect.objectContaining({ credentials: 'same-origin' }),
      )
    })
    expect(screen.getByRole('heading', { name: 'Situation actuelle' })).toBeInTheDocument()

    expect(tunnel!).not.toHaveTextContent(/proxy|M2|wedge|Secteurs non résolus|Détail analytique/i)
    expect(within(tunnel!).queryByText('Réponses positives')).not.toBeInTheDocument()
  })

  it('garde la période chargée visible et permet de retenter une sélection en échec', async () => {
    const user = userEvent.setup()
    let todayAttempts = 0
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/overview') && url.includes('period=today')) {
        todayAttempts += 1
        return { ok: false, status: 503 }
      }
      return {
        ok: true,
        status: 200,
        json: async () => (url.includes('/overview') ? OVERVIEW : SESSION),
      }
    }))

    render(<FounderApp />)
    await screen.findByRole('heading', { name: 'Tunnel commercial' })

    await user.click(screen.getByRole('button', { name: 'Aujourd’hui' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('pas encore disponibles')
    expect(screen.getByRole('button', { name: 'Aujourd’hui' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: '7 derniers jours' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(screen.getByRole('tabpanel', { name: 'Période' })).getByText('Envoyés').closest('article')).toHaveTextContent('11')

    await user.click(screen.getByRole('button', { name: 'Aujourd’hui' }))
    await waitFor(() => expect(todayAttempts).toBe(2))
  })

  it('déplace la sélection des onglets du tunnel avec les flèches', async () => {
    const user = userEvent.setup()
    installSuccessfulFetch()

    render(<FounderApp />)
    await screen.findByRole('heading', { name: 'Tunnel commercial' })
    const periodTab = screen.getByRole('tab', { name: 'Période' })
    const cohortTab = screen.getByRole('tab', { name: 'Par cohorte' })

    expect(periodTab).toHaveAttribute('tabindex', '0')
    expect(cohortTab).toHaveAttribute('tabindex', '-1')
    periodTab.focus()
    await user.keyboard('{ArrowRight}')
    expect(cohortTab).toHaveFocus()
    expect(cohortTab).toHaveAttribute('aria-selected', 'true')
    expect(periodTab).toHaveAttribute('tabindex', '-1')

    await user.keyboard('{ArrowLeft}')
    expect(periodTab).toHaveFocus()
    expect(periodTab).toHaveAttribute('aria-selected', 'true')
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
    expect(screen.queryByRole('heading', { name: 'Aujourd’hui', level: 1 })).not.toBeInTheDocument()
  })
})
