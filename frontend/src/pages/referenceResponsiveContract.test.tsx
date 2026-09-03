import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  ICP,
  ME,
  PRO_STATUS,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  factualFallbackPresentation,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

function mobileMatchMedia(query: string): MediaQueryList {
  return {
    matches: query.includes('max-width'),
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

const PUBLISHED_HEADLINE = 'Attribution documentée pour le lot communal de voirie'
const PUBLISHED_AWARD_SUMMARY = 'La source officielle documente l’attribution de ce lot communal.'

const PUBLISHED_UNLOCKED_ITEM = {
  ...UNLOCKED_ITEM,
  presentation: factualFallbackPresentation({
    artifactId: '1'.repeat(64),
    headline: PUBLISHED_HEADLINE,
    awardSummary: PUBLISHED_AWARD_SUMMARY,
    headlineEvidenceRefs: ['source:notice:26-104412:headline'],
    awardSummaryEvidenceRefs: ['source:notice:26-104412:award-summary'],
  }),
}

const PUBLISHED_UNLOCKED_DETAIL = {
  ...UNLOCKED_DETAIL,
  presentation: PUBLISHED_UNLOCKED_ITEM.presentation,
}

describe('contrat responsive connecté à 390 px', () => {
  /* Sous 900 px, le détail s'ouvre en feuille modale (Radix `Sheet`) : le h2
   * du tiroir porte le titre du marché (`lot_title ?? title ?? object_short`,
   * jamais le résumé commercial), et le chrome applicatif derrière la feuille
   * devient inerte tant qu'elle reste ouverte — un seul `<main>`, un seul
   * `h1` existent structurellement, et la navigation mobile n'est plus
   * atteignable par le clavier ou le lecteur d'écran pendant ce temps. */
  it('conserve un main, un h1, ouvre le détail en feuille modale et rend le chrome inerte', async () => {
    vi.stubGlobal('matchMedia', mobileMatchMedia)
    vi.stubGlobal('innerWidth', 390)
    mockSignalRoute()

    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    await screen.findByRole('heading', { level: 2, name: 'Voirie' })
    // Radix marque le fond `aria-hidden` tant que la feuille modale reste
    // ouverte : `getAllByRole('main'|'heading')` ne les y trouverait plus,
    // d'où une requête DOM directe pour vérifier leur unicité structurelle.
    expect(document.querySelectorAll('main')).toHaveLength(1)
    expect(document.querySelectorAll('h1')).toHaveLength(1)
    expect(screen.queryByRole('button', { name: 'Ouvrir la navigation' })).not.toBeInTheDocument()

    const sheet = screen.getByRole('dialog')
    expect(within(sheet).getAllByRole('button', { name: 'Fermer' }).length).toBeGreaterThan(0)
  })

  it('confine le focus dans le drawer puis le rend au déclencheur avec Échap et le scrim', async () => {
    vi.stubGlobal('matchMedia', mobileMatchMedia)
    vi.stubGlobal('innerWidth', 390)
    const user = userEvent.setup()
    mockSignalRoute()
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    await screen.findByRole('heading', { level: 1, name: 'Signaux' })
    const trigger = screen.getByRole('button', { name: 'Ouvrir la navigation' })
    await user.click(trigger)

    let drawer = screen.getByRole('dialog', { name: 'Navigation' })
    const first = within(drawer).getByRole('link', { name: 'Kivou, vue d’ensemble' })
    const last = within(drawer).getByRole('button', { name: 'Fermer' })
    expect(document.querySelector('[data-slot="sheet-overlay"]')).not.toBeNull()
    expect(drawer).toContainElement(document.activeElement as HTMLElement)

    last.focus()
    await user.tab()
    expect(first).toHaveFocus()
    await user.tab({ shift: true })
    expect(last).toHaveFocus()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()

    await user.click(trigger)
    drawer = screen.getByRole('dialog', { name: 'Navigation' })
    expect(drawer).toBeVisible()
    const overlay = document.querySelector<HTMLElement>('[data-slot="sheet-overlay"]')
    expect(overlay).not.toBeNull()
    await user.click(overlay!)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('ferme le drawer après une navigation interne réelle', async () => {
    vi.stubGlobal('matchMedia', mobileMatchMedia)
    vi.stubGlobal('innerWidth', 390)
    const user = userEvent.setup()
    mockSignalRoute()
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    await screen.findByRole('heading', { level: 1, name: 'Signaux' })
    await user.click(screen.getByRole('button', { name: 'Ouvrir la navigation' }))
    const drawer = screen.getByRole('dialog', { name: 'Navigation' })
    await user.click(within(drawer).getByRole('link', { name: 'Vue d’ensemble' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' })).toBeVisible()
  })

  it('localise le drawer et le ferme avec retour focus sur sa destination déjà active', async () => {
    vi.stubGlobal('matchMedia', mobileMatchMedia)
    vi.stubGlobal('innerWidth', 390)
    const user = userEvent.setup()
    const session = {
      status: 'authenticated' as const,
      me: { ...ME, locale: 'en' as const },
    }
    mockSignalRoute()
    renderApp(<AppRoutes />, { route: '/app/signals', session, locale: 'en' })

    await screen.findByRole('heading', { level: 1, name: 'Signals' })
    const trigger = screen.getByRole('button', { name: 'Open navigation' })
    await user.click(trigger)
    const drawer = screen.getByRole('dialog', { name: 'Navigation' })
    expect(drawer).toHaveAccessibleDescription('Kivou main menu.')
    expect(within(drawer).getByRole('button', { name: 'Close' })).toBeVisible()
    expect(within(drawer).queryByRole('button', { name: 'Fermer' })).not.toBeInTheDocument()

    await user.click(within(drawer).getByRole('link', { name: 'Signals' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('préserve exactement les breakpoints et la réduction de mouvement approuvés', () => {
    const css = readFileSync(
      join(process.cwd(), 'src/reference/dashboard/dashboard-reference.css'),
      'utf8',
    )
    const media = [...css.matchAll(/@media\s*\(([^)]+)\)/g)].map((match) => match[1])
    expect(media).toEqual([
      'max-width: 1279px',
      'min-width: 768px',
      'max-width: 1599px',
      'max-width: 1179px',
      'max-width: 820px',
      'max-width: 620px',
      'prefers-reduced-motion: reduce',
    ])
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*scroll-behavior:\s*auto/)
  })
})

function mockSignalRoute() {
  mockApi({
    'GET /signals': { body: feedPage([PUBLISHED_UNLOCKED_ITEM]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: PUBLISHED_UNLOCKED_DETAIL },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
      body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
    },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: PRO_STATUS },
  })
}
