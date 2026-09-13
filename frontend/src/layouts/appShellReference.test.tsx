import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { AUTHENTICATED, DISCOVERY_STATUS, ICP, mockApi, renderApp } from '../test/harness'
import type { Routes } from '../test/harness'

const EMPTY_DASHBOARD = {
  as_of: '2026-09-04', last_seen_at: null, new_since_last_visit: 0,
  strong_matches: 0, top3: [], to_follow_up: [], to_follow_up_truncated: false,
  week: { new: 0, saved: 0, contacted: 0, replied: 0 }, scan_truncated: false,
  profile: { name: ICP.label, sector_label: 'Routes et génie civil', zone_labels: ICP.customer_input.territories },
  plan: { name: 'Découverte', opened: 0, quota: 3, period_end: null },
}

afterEach(() => vi.unstubAllGlobals())

describe('shell Kivou', () => {
  it('n’invente pas de compteurs quand le résumé échoue', async () => {
    mockConnectedApi({ 'GET /dashboard': { status: 503, body: { detail: 'unavailable' } } })
    renderApp(<AppRoutes />, { route: '/app', session: AUTHENTICATED })
    await screen.findByRole('heading', { name: 'Votre journée n’a pas pu être chargée' })
    const summary = document.querySelector<HTMLElement>('.sidebar-plan-summary')!
    expect(summary).not.toHaveTextContent('0/∞')
    expect(summary).not.toHaveTextContent('0 signaux')
    expect(summary).toHaveTextContent('Résumé temporairement indisponible')
  })
  it('affiche les six destinations dans l’ordre demandé', async () => {
    mockConnectedApi()
    renderApp(<AppRoutes />, { route: '/app', session: AUTHENTICATED })
    await screen.findByRole('heading', { name: 'Aujourd’hui' })
    await screen.findByRole('heading', { name: 'Vos priorités commerciales' })

    const navigation = document.querySelector<HTMLElement>('.sidebar-menu')!
    const links = within(navigation).getAllByRole('link')
    expect(links.map((link) => link.textContent?.trim())).toEqual([
      'Aujourd’hui', 'Signaux', 'Entreprises', 'Profil cible', 'Alertes', 'Réglages',
    ])
    expect(links.map((link) => link.getAttribute('href')?.split('?')[0])).toEqual([
      '/app/dashboard', '/app/signals', '/app/companies', '/app/icps',
      '/app/notifications', '/app/settings',
    ])
    for (const link of links.slice(0, 3)) expect(new URL(link.getAttribute('href')!, 'https://kivou.test').searchParams.get('target_icp_id')).toBe(ICP.target_icp_id)
    expect(links[0]).toHaveAttribute('aria-current', 'page')
  })

  it('affiche le plan, les signaux ouverts, le secteur et les zones en bas du menu', async () => {
    mockConnectedApi()
    renderApp(<AppRoutes />, { route: '/app', session: AUTHENTICATED })
    await screen.findByRole('heading', { name: 'Vos priorités commerciales' })
    const summary = document.querySelector<HTMLElement>('.sidebar-plan-summary')!
    expect(summary).toHaveTextContent('Plan Découverte')
    expect(summary).toHaveTextContent('signaux ce mois')
    expect(summary).toHaveTextContent('Routes et génie civil')
    expect(summary).toHaveTextContent('France')
    expect(summary).not.toHaveTextContent(/\bFR\b/)
  })

  it.each([['/app/notifications', 'Alertes'], ['/app/settings', 'Réglages']])(
    'marque la destination active pour %s',
    async (route, label) => {
      mockConnectedApi()
      renderApp(<AppRoutes />, { route, session: AUTHENTICATED })
      expect(await screen.findByRole('link', { name: label })).toHaveAttribute('aria-current', 'page')
    },
  )
})

function mockConnectedApi(overrides: Routes = {}) {
  mockApi({
    'GET /dashboard': { body: EMPTY_DASHBOARD },
    'GET /target-icps': { body: [ICP] },
    'GET /target-icps/options': { body: { zones: [], sectors: [] } },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /notification-preferences': {
      body: { email_enabled: false, notification_email: null, updated_at: '2026-09-04' },
    },
    ...overrides,
  })
}
