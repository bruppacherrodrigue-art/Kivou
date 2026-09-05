import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import type { UnlockedFeedItem } from '../api/types'
import { AUTHENTICATED, ICP, PRO_STATUS, UNLOCKED_ITEM, callsTo, mockApi, renderApp } from '../test/harness'

const signal = (index: number): UnlockedFeedItem => ({
  ...UNLOCKED_ITEM,
  signal_id: `sig_${index}`,
  company_key: `cmp_company_${index}_abcdef`,
  company: { ...UNLOCKED_ITEM.company, name: `Titulaire ${index}` },
  factual_display: { ...UNLOCKED_ITEM.factual_display, object_short: `Marché prioritaire ${index}`, market_summary: `Marché prioritaire ${index}` },
  contract: { ...UNLOCKED_ITEM.contract, lot_title: null, title: `Marché prioritaire ${index}`, amount: { value: `${index}00000`, currency: 'EUR' } },
  analysis: { ...UNLOCKED_ITEM.analysis, fit: { ...UNLOCKED_ITEM.analysis.fit, reasons: [`Libellé de règle ${index}`], for_you_sentence: `Phrase rédigée ${index}.` } },
})

const signals = [signal(1), signal(2), signal(3), signal(4)]

function dashboard(top3 = signals.slice(0, 3), firstVisit = false) {
  return {
    as_of: '2026-09-04',
    last_seen_at: firstVisit ? null : '2026-09-01T09:00:00+00:00',
    new_since_last_visit: firstVisit ? 0 : 12,
    strong_matches: firstVisit ? 0 : 3,
    top3,
    to_follow_up: firstVisit ? [] : [{ company_key: 'cmp_follow_up_abcdef', name: 'Amiaud SARL', last_signal: { ...signal(9), contract: { ...signal(9).contract, title: 'CVC plomberie' } }, days_since_contact: 9 }],
    to_follow_up_truncated: false,
    week: { new: 12, saved: 5, contacted: 3, replied: 1 },
    scan_truncated: false,
    profile: { name: ICP.label, sector_label: 'Routes et génie civil', zone_labels: ICP.customer_input.territories },
    plan: { name: 'Pro', opened: 2, quota: 3, period_end: null },
  }
}

function routes(payload = dashboard()) {
  return {
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: PRO_STATUS },
    'GET /dashboard': { body: payload },
    'PUT /signals/sig_1/feedback': { body: { signal_id: 'sig_1', interaction: null } },
  }
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('Aujourd’hui', () => {
  it('affiche le bandeau, trois cartes et leur phrase rédigée partagée', async () => {
    mockApi(routes())
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    expect(await screen.findByRole('heading', { name: '12 nouveaux marchés depuis mardi' })).toBeVisible()
    expect(screen.getByText(/3 correspondent fortement à votre profil/)).toHaveTextContent('Routes et génie civil')
    expect(screen.getAllByRole('article')).toHaveLength(3)
    for (const index of [1, 2, 3]) {
      expect(screen.getByText(`Titulaire ${index}`)).toBeVisible()
      expect(screen.getByText(`Phrase rédigée ${index}.`)).toBeVisible()
      expect(screen.queryByText(`Libellé de règle ${index}`)).not.toBeInTheDocument()
    }
  })

  it('ouvre le drawer partagé depuis une carte', async () => {
    mockApi(routes())
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    const user = userEvent.setup()
    const card = (await screen.findByText('Titulaire 1')).closest('article')!
    await user.click(within(card).getByRole('button', { name: 'Ouvrir' }))
    expect(screen.getByRole('complementary', { name: 'Marché prioritaire 1' })).toBeVisible()
  })

  it('ignore une priorité et charge la suivante', async () => {
    let reads = 0
    mockApi({ ...routes(), 'GET /dashboard': () => ({ body: reads++ === 0 ? dashboard() : dashboard(signals.slice(1, 4)) }) })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    const user = userEvent.setup()
    const card = (await screen.findByText('Titulaire 1')).closest('article')!
    await user.click(within(card).getByRole('button', { name: 'Ignorer' }))
    await screen.findByText('Titulaire 4')
    expect(screen.queryByText('Titulaire 1')).not.toBeInTheDocument()
    expect(callsTo('/signals/sig_1/feedback', 'PUT')[0].body).toEqual({ relevance: 'not_relevant' })
  })

  it('affiche les relances et les compteurs de la semaine', async () => {
    mockApi(routes())
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    const followUp = await screen.findByRole('region', { name: 'À relancer' })
    expect(within(followUp).getByText('Amiaud SARL')).toBeVisible()
    expect(within(followUp).getByText('CVC plomberie')).toBeVisible()
    expect(within(followUp).getByText('contactée il y a 9 j')).toBeVisible()
    expect(within(followUp).getByRole('link', { name: 'Ouvrir' })).toHaveAttribute('href', '/app/companies/cmp_follow_up_abcdef')
    const week = screen.getByRole('region', { name: 'Cette semaine' })
    for (const value of ['12', '5', '3', '1']) expect(within(week).getByText(value)).toBeVisible()
  })

  it('affiche les états vides et le titre de première visite', async () => {
    mockApi(routes(dashboard([], true)))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard' })
    expect(await screen.findByRole('heading', { name: 'Vos premiers signaux' })).toBeVisible()
    expect(screen.getByText('Aucun nouveau signal prioritaire pour le moment.')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Voir tous les signaux' })).toHaveAttribute('href', '/app/signals')
    expect(screen.getByText('Aucune entreprise à relancer.')).toBeVisible()
  })

  it('fait de /app la page Aujourd’hui', async () => {
    mockApi(routes())
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app' })
    await waitFor(() => expect(callsTo('/dashboard', 'GET')).toHaveLength(1))
    expect(screen.getByRole('heading', { name: '12 nouveaux marchés depuis mardi' })).toBeVisible()
  })

  it('annonce une semaine active sans prétendre avoir du nouveau et déduplique les zones', async () => {
    const payload = dashboard()
    payload.new_since_last_visit = 0
    payload.week.new = 7
    payload.profile.zone_labels = ['FR', 'France', 'Vaud', 'Vaud']
    mockApi(routes(payload))
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app' })

    expect(await screen.findByRole('heading', { name: 'Rien de nouveau depuis mardi · 7 signaux cette semaine' })).toBeVisible()
    const subtitle = screen.getAllByText(/Routes et génie civil/).find((node) => node.tagName === 'P')!
    expect(subtitle).toHaveTextContent('France, Vaud')
    expect(subtitle).not.toHaveTextContent('FR,')
  })
})
