import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
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
  it('conserve un main, un h1, la navigation mobile et un retour vers la liste', async () => {
    vi.stubGlobal('matchMedia', mobileMatchMedia)
    vi.stubGlobal('innerWidth', 390)
    mockSignalRoute()

    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    await screen.findByRole('heading', {
      name: PUBLISHED_UNLOCKED_DETAIL.presentation.content.headline,
    })
    expect(screen.queryByRole('heading', { name: UNLOCKED_ITEM.contract.title! })).toBeNull()
    expect(screen.getAllByRole('main')).toHaveLength(1)
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Ouvrir la navigation' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Retour à la liste' })).toBeVisible()
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

  it('focalise le titre du détail puis rend le focus à la ligne choisie', async () => {
    vi.stubGlobal('matchMedia', mobileMatchMedia)
    vi.stubGlobal('innerWidth', 390)
    const user = userEvent.setup()
    const second = {
      ...PUBLISHED_UNLOCKED_ITEM,
      signal_id: 'sig_mobile_2',
      company: { ...UNLOCKED_ITEM.company, name: 'Deuxième entreprise mobile' },
      contract: { ...UNLOCKED_ITEM.contract, title: 'Deuxième marché mobile' },
      presentation: factualFallbackPresentation({
        artifactId: '6'.repeat(64),
        headline: 'Présentation publiée pour le second signal mobile',
        awardSummary: 'La source mobile documente la seconde attribution publiée.',
        headlineEvidenceRefs: ['source:mobile:second:headline'],
        awardSummaryEvidenceRefs: ['source:mobile:second:award-summary'],
      }),
    }
    const secondDetail = { ...PUBLISHED_UNLOCKED_DETAIL, ...second, company_key: 'cmp_mobile_2' }
    mockApi({
      'GET /signals': { body: feedPage([PUBLISHED_UNLOCKED_ITEM, second]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: PUBLISHED_UNLOCKED_DETAIL },
      [`GET /signals/${second.signal_id}`]: { body: secondDetail },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
      },
      [`GET /signals/${second.signal_id}/note`]: {
        body: { signal_id: second.signal_id, note: null, updated_at: null },
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    const row = await screen.findByRole('button', { name: /Deuxième entreprise mobile/ })
    await user.click(row)
    const heading = await screen.findByRole('heading', {
      name: second.presentation.content.headline,
    })
    expect(screen.queryByRole('heading', { name: second.contract.title })).toBeNull()
    await waitFor(() => expect(heading).toHaveFocus())

    await user.click(screen.getByRole('button', { name: 'Retour à la liste' }))
    await waitFor(() => expect(row).toHaveFocus())
  })

  it('conserve la demande de focus jusqu’à la réponse terminale du détail', async () => {
    vi.stubGlobal('matchMedia', mobileMatchMedia)
    vi.stubGlobal('innerWidth', 390)
    const user = userEvent.setup()
    let resolveDetail!: (value: { body: typeof UNLOCKED_DETAIL }) => void
    const second = {
      ...PUBLISHED_UNLOCKED_ITEM,
      signal_id: 'sig_mobile_delayed',
      company: { ...UNLOCKED_ITEM.company, name: 'Entreprise mobile différée' },
      contract: { ...UNLOCKED_ITEM.contract, title: 'Marché mobile différé' },
      presentation: factualFallbackPresentation({
        artifactId: '7'.repeat(64),
        headline: 'Présentation publiée pour le signal mobile différé',
        awardSummary: 'La source mobile documente l’attribution publiée après chargement.',
        headlineEvidenceRefs: ['source:mobile:delayed:headline'],
        awardSummaryEvidenceRefs: ['source:mobile:delayed:award-summary'],
      }),
    }
    const secondDetail = { ...PUBLISHED_UNLOCKED_DETAIL, ...second, company_key: 'cmp_mobile_delayed' }
    mockApi({
      'GET /signals': { body: feedPage([PUBLISHED_UNLOCKED_ITEM, second]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: PUBLISHED_UNLOCKED_DETAIL },
      [`GET /signals/${second.signal_id}`]: () => new Promise((resolve) => { resolveDetail = resolve }),
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
      },
      [`GET /signals/${second.signal_id}/note`]: {
        body: { signal_id: second.signal_id, note: null, updated_at: null },
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    await user.click(await screen.findByRole('button', { name: /Entreprise mobile différée/ }))
    await screen.findByRole('heading', { name: 'Chargement…' })
    await act(async () => resolveDetail({ body: secondDetail }))

    const heading = await screen.findByRole('heading', {
      name: second.presentation.content.headline,
    })
    expect(screen.queryByRole('heading', { name: second.contract.title })).toBeNull()
    await waitFor(() => expect(heading).toHaveFocus())
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
