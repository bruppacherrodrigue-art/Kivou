import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import type { WeeklyCommercialCockpit } from '../api/types'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  ME,
  callsTo,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const REPORT: WeeklyCommercialCockpit = {
  report_version: 'weekly-commercial-cockpit-v1',
  report_ref: 'a'.repeat(64),
  week_start: '2026-08-10T00:00:00+02:00',
  week_end: '2026-08-17T00:00:00+02:00',
  captured_at: '2026-08-17T00:00:00+02:00',
  timezone: 'Europe/Zurich',
  delivery_semantics: 'PROXY_SENT_MINUS_BOUNCE_V1',
  funnel: {
    delivered_proxy_count: 10,
    positive_reply_count: 3,
    click_count: 2,
    activated_account_count: 2,
    paid_account_count: 1,
    mrr_by_currency: [
      { currency: 'CHF', minor_units: 9900 },
      { currency: 'EUR', minor_units: 4900 },
    ],
    churn_count: 1,
  },
  analytical_rows: [
    {
      country: 'CH',
      sector_ref: 'sector-construction',
      need_ref: 'workforce_capacity',
      campaign_ref: 'campaign-ref-safe',
      delivered_proxy_count: 10,
      positive_reply_count: 3,
      click_count: 2,
      activated_account_count: 2,
      paid_account_count: 1,
      mrr_by_currency: [{ currency: 'CHF', minor_units: 9900 }],
      churn_count: 1,
      positive_reply_rate: '0.300000',
      click_rate: '0.200000',
      activation_rate: '0.200000',
      paid_rate: '0.100000',
    },
  ],
  wedge_m2_efficiency: [
    {
      wedge: 'construction',
      currency: 'CHF',
      m2_eligible_delivered_proxy_count: 8,
      retained_m2_accounts: 1,
      retained_m2_mrr_minor_units: 9900,
      retained_m2_mrr_per_1000_delivered: '1237500.000000',
      data_status: 'READY',
    },
    {
      wedge: 'maintenance',
      currency: null,
      m2_eligible_delivered_proxy_count: 0,
      retained_m2_accounts: 0,
      retained_m2_mrr_minor_units: null,
      retained_m2_mrr_per_1000_delivered: null,
      data_status: 'INSUFFICIENT_M2_EVIDENCE',
    },
  ],
  data_quality: {
    delivery_is_proxy: true,
    unresolved_sector_count: 0,
    unknown_mrr_journey_count: 1,
    m2_insufficient_wedges: ['maintenance'],
    captured_at: '2026-08-17T00:00:00+02:00',
  },
}

const OPERATOR = {
  status: 'authenticated' as const,
  me: { ...ME, capabilities: { commercial_cockpit: true } },
}

describe('cockpit commercial interne', () => {
  it('cache la navigation au client normal et refuse la route manuelle sans appeler les données', async () => {
    mockApi({
      'GET /signals': { body: feedPage([]) },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/internal/cockpit' })

    expect(screen.getByRole('heading', { name: 'Accès interne requis' })).toBeInTheDocument()
    expect(await screen.findByText(`${ICP.label} · ${ICP.customer_input.territories[0]}`)).toBeVisible()
    expect(screen.queryByRole('link', { name: 'Cockpit commercial' })).not.toBeInTheDocument()
    expect(callsTo('/internal/commercial-cockpit', 'GET')).toHaveLength(0)
  })

  it('rend le funnel, les devises, le proxy, M2 et la table sans donnée client', async () => {
    mockApi({
      'GET /internal/commercial-cockpit': { body: REPORT },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, { session: OPERATOR, route: '/app/internal/cockpit' })

    expect(await screen.findByRole('heading', { name: 'Cockpit commercial' })).toBeInTheDocument()
    expect(await screen.findByText(`${ICP.label} · ${ICP.customer_input.territories[0]}`)).toBeVisible()
    expect(screen.queryByRole('link', { name: 'Cockpit commercial' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Compte' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getAllByText('Emails délivrés (proxy)').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/99/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/^49/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Donnée incomplète')).toBeInTheDocument()
    expect(
      screen.getByRole('heading', {
        name: 'MRR M2 retenu / 1 000 emails délivrés (proxy)',
      }),
    ).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Pays × secteur × besoin × campagne' })
    expect(within(table).getByText('campaign-ref-safe')).toBeInTheDocument()
    expect(within(table).getByText('workforce_capacity')).toBeInTheDocument()
    const body = document.body.textContent ?? ''
    for (const pii of (
      ['lead@example.invalid', 'signup@example.invalid', 'pi_123', 'provider-lead-1']
    )) {
      expect(body).not.toContain(pii)
    }
  })

  it('borne le sélecteur à 52 semaines et recharge une semaine historique au clavier', async () => {
    const user = userEvent.setup()
    mockApi({
      'GET /internal/commercial-cockpit': ({ search }) => ({
        body: { ...REPORT, report_ref: (search.get('week_offset') ?? '0').padStart(64, '0') },
      }),
    })
    renderApp(<AppRoutes />, { session: OPERATOR, route: '/app/internal/cockpit' })

    const selector = await screen.findByRole('combobox', { name: 'Semaine terminée' })
    expect(within(selector).getAllByRole('option')).toHaveLength(52)
    await user.selectOptions(selector, '1')
    await waitFor(() => {
      expect(
        callsTo('/internal/commercial-cockpit', 'GET').some(
          (call) => call.search.get('week_offset') === '1',
        ),
      ).toBe(true)
    })
  })

  it('affiche honnêtement les états vide et erreur', async () => {
    const empty = {
      ...REPORT,
      funnel: {
        delivered_proxy_count: 0,
        positive_reply_count: 0,
        click_count: 0,
        activated_account_count: 0,
        paid_account_count: 0,
        mrr_by_currency: [],
        churn_count: 0,
      },
      analytical_rows: [],
      wedge_m2_efficiency: [],
      data_quality: { ...REPORT.data_quality, unknown_mrr_journey_count: 0 },
    }
    mockApi({ 'GET /internal/commercial-cockpit': { body: empty } })
    const view = renderApp(<AppRoutes />, {
      session: OPERATOR,
      route: '/app/internal/cockpit',
    })
    expect(await screen.findByText('Aucune activité sortante pour cette semaine.')).toBeInTheDocument()

    view.unmount()
    mockApi({ 'GET /internal/commercial-cockpit': { status: 500, body: {} } })
    renderApp(<AppRoutes />, { session: OPERATOR, route: '/app/internal/cockpit' })
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Le cockpit est momentanément indisponible.',
    )
  })
})
