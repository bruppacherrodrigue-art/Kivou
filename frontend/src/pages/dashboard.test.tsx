import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import type { DashboardResponse, UnlockedFeedItem } from '../api/types'
import { AUTHENTICATED, ICP, PRO_STATUS, UNLOCKED_ITEM, callsTo, mockApi, renderApp } from '../test/harness'

const signal = (index: number): UnlockedFeedItem => ({
  ...UNLOCKED_ITEM,
  status_revision: 0,
  signal_id: `sig_${index}`,
  company_key: `cmp_company_${index}_abcdef`,
  company: { ...UNLOCKED_ITEM.company, name: `Titulaire ${index}` },
  factual_display: { ...UNLOCKED_ITEM.factual_display, object_short: `Marché prioritaire ${index}`, market_summary: `Marché prioritaire ${index}` },
  contract: { ...UNLOCKED_ITEM.contract, lot_title: null, title: `Marché prioritaire ${index}`, amount: { value: `${index}00000`, currency: 'EUR' } },
  analysis: { ...UNLOCKED_ITEM.analysis, fit: { ...UNLOCKED_ITEM.analysis.fit, reasons: [`Libellé de règle ${index}`], for_you_sentence: `Phrase rédigée ${index}.` } },
})

const signals = [signal(1), signal(2), signal(3), signal(4)]

function dashboard(top3 = signals.slice(0, 3), firstVisit = false): DashboardResponse {
  return {
    as_of: '2026-09-04',
    last_seen_at: firstVisit ? null : '2026-09-01T09:00:00+00:00',
    new_since_last_visit: firstVisit ? 0 : 12,
    strong_matches: firstVisit ? 0 : 3,
    top3,
    to_follow_up: firstVisit ? [] : [{
      company_key: 'cmp_follow_up_abcdef',
      name: 'Amiaud SARL',
      last_signal: {
        ...signal(9),
        factual_display: {
          ...signal(9).factual_display,
          object_short: 'CVC plomberie',
          market_summary: 'CVC plomberie',
        },
        contract: { ...signal(9).contract, title: 'CVC plomberie' },
      },
      days_since_contact: 9,
    }],
    to_follow_up_truncated: false,
    week: { new: 12, saved: 5, contacted: 3, replied: 1 },
    scan_truncated: false,
    profile: { name: ICP.label, sector_label: 'Routes et génie civil', zone_labels: ICP.customer_input.territories },
    plan: { code: 'pro', name: 'Pro', assigned: null, opened_this_month: 2, quota: null, remaining: null, availability: null, period_end: null },
  }
}

function routes(payload = dashboard()) {
  return {
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: PRO_STATUS },
    'GET /dashboard': { body: payload },
    'GET /companies': { body: { items: [], counts: {}, page: { has_more: false } } },
    'GET /target-icps/options': { body: { zones: [], sectors: [] } },
    'GET /signals/sig_1/note': { body: { note: null, revision: 0, updated_at: null } },
    'PUT /signals/sig_1/status': { body: { signal_id: 'sig_1', status: 'ignored', revision: 1, updated_at: '2026-09-13T10:00:00Z', interaction: null } },
  }
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('Aujourd’hui', () => {
  it('affiche le ciblage et trois priorités, sans répéter les anciennes phrases statiques', async () => {
    mockApi(routes())
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    expect(await screen.findByText('12 nouveaux marchés depuis votre dernière visite.')).toBeVisible()
    expect(screen.getAllByRole('button', { name: 'Ajuster' })).toHaveLength(1)
    expect(screen.getAllByRole('article')).toHaveLength(3)
    for (const index of [1, 2, 3]) {
      expect(screen.getByText(`Titulaire ${index}`)).toBeVisible()
      expect(screen.queryByText(`Phrase rédigée ${index}.`)).not.toBeInTheDocument()
      expect(screen.queryByText(`Libellé de règle ${index}`)).not.toBeInTheDocument()
    }
  })

  it('ouvre le drawer partagé depuis une carte', async () => {
    const detail = {
      ...signal(1),
      holder_history: {
        resolution: 'company_key' as const,
        last_12_months: { awards_count: 3 },
        summary: { consortium_share: '0.0' },
        source: 'public_awards' as const,
      },
    }
    mockApi({ ...routes(), 'GET /signals/sig_1': { body: detail } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    const user = userEvent.setup()
    const card = (await screen.findByText('Titulaire 1')).closest('article')!
    await user.click(within(card).getByRole('button', { name: 'Ouvrir : Marché prioritaire 1' }))
    const drawer = screen.getByRole('dialog', { name: 'Détail du signal' })
    expect(await within(drawer).findByRole('heading', { name: 'Marché prioritaire 1' })).toBeVisible()
    expect(within(drawer).getByRole('textbox', { name: 'Vos notes sur ce signal' })).toBeVisible()
    expect(callsTo('/signals/sig_1', 'GET')).toHaveLength(1)
  })

  it('ne réintroduit pas de démarrage estimé dans les priorités', async () => {
    const timed = {
      ...signal(1),
      commercial_calendar: { start_month: '2026-10', duration_months: 8, source: 'public_notice' as const },
    }
    mockApi(routes(dashboard([timed])))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    await screen.findByRole('heading', { name: 'Vos priorités commerciales' })
    expect(screen.queryByText(/Démarrage probable/)).not.toBeInTheDocument()
  })

  it('ignore une priorité et charge la suivante', async () => {
    let reads = 0
    mockApi({ ...routes(), 'GET /dashboard': () => ({ body: reads++ === 0 ? dashboard() : dashboard(signals.slice(1, 4)) }) })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    const user = userEvent.setup()
    const card = (await screen.findByText('Titulaire 1')).closest('article')!
    await user.click(within(card).getByRole('button', { name: 'Ignorer le signal' }))
    await screen.findByText('Titulaire 4')
    expect(screen.queryByText('Titulaire 1')).not.toBeInTheDocument()
    expect(callsTo('/signals/sig_1/status', 'PUT')[0].body).toEqual({ status: 'ignored', expected_revision: 0 })
  })

  it('affiche les relances et les compteurs de la semaine', async () => {
    mockApi(routes())
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    const followUp = await screen.findByRole('region', { name: 'Entreprises à relancer' })
    expect(within(followUp).getByText('Amiaud SARL')).toBeVisible()
    expect(within(followUp).getByText('Dernier contact il y a 9 jours')).toBeVisible()
    expect(within(followUp).getByRole('link', { name: 'Amiaud SARL' })).toHaveAttribute('href', expect.stringContaining('/app/companies/cmp_follow_up_abcdef'))
    const week = screen.getByRole('region', { name: 'Bilan de la semaine' })
    for (const value of ['12 nouveaux signaux', '5 sauvegardés', '3 contactés', '1 réponses']) expect(within(week).getByText(value)).toBeVisible()
  })

  it('affiche les états vides et le titre de première visite', async () => {
    mockApi(routes(dashboard([], true)))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    expect(await screen.findByRole('heading', { name: 'Vous êtes à jour' })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Tous les signaux' })).toHaveAttribute('href', expect.stringContaining('/app/signals'))
    expect(screen.getByRole('link', { name: 'Reprendre mes signaux sauvegardés' })).toHaveAttribute('href', expect.stringContaining('status=saved'))
    expect(screen.getByText('Vos prochaines relances se préparent ici')).toBeVisible()
  })

  it('explique un compte Découverte à 0/3 sans prétendre qu’il est à jour', async () => {
    const payload = dashboard([], true)
    payload.plan = { code: 'discovery', name: 'Découverte', assigned: 0, opened_this_month: null, quota: 3, remaining: 3, availability: 'preparing', period_end: null }
    mockApi(routes(payload))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText('Vos 3 signaux sont en préparation. Kivou sélectionne les meilleures opportunités disponibles.')).toBeVisible()
    expect(screen.queryByRole('heading', { name: 'Vous êtes à jour' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Reprendre mes signaux sauvegardés' })).not.toBeInTheDocument()
  })

  it('annonce le reliquat Découverte après deux attributions', async () => {
    const payload = dashboard(signals.slice(0, 2), true)
    payload.plan = { code: 'discovery', name: 'Découverte', assigned: 2, opened_this_month: null, quota: 3, remaining: 1, availability: 'partial', period_end: null }
    mockApi(routes(payload))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })

    expect(await screen.findByText('2 de vos 3 signaux sont disponibles. Kivou prépare le suivant.')).toBeVisible()
    expect(screen.getAllByRole('article')).toHaveLength(2)
  })

  it('fait de /app la page Aujourd’hui', async () => {
    mockApi(routes())
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app' })
    await waitFor(() => expect(callsTo('/dashboard', 'GET')).toHaveLength(1))
    expect(screen.getByRole('heading', { name: 'Aujourd’hui' })).toBeVisible()
  })

  it('annonce une semaine active sans prétendre avoir du nouveau et déduplique les zones', async () => {
    const payload = dashboard()
    payload.new_since_last_visit = 0
    payload.week.new = 7
    payload.profile!.zone_labels = ['FR', 'France', 'Vaud', 'Vaud']
    mockApi(routes(payload))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app' })

    expect(await screen.findByText('7 nouveaux signaux')).toBeVisible()
    expect(screen.queryByText(/nouveaux marchés depuis/)).not.toBeInTheDocument()
    const summary = document.querySelector('.sidebar-plan-summary')!
    expect(summary).toHaveTextContent('France, Vaud')
    expect(summary).not.toHaveTextContent('FR,')
  })
})
