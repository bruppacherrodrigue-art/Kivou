import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  ME,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  feedPage,
  mockApi,
  renderApp,
  UNAUTHENTICATED,
} from '../test/harness'

const read = (path: string) => readFileSync(join(process.cwd(), path), 'utf8')

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function renderSignalsShell() {
  mockApi({
    'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
    'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
    'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /target-icps': { body: [ICP] },
  })
  return renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })
}

function stubMobileMedia() {
  const query = '(max-width: 767px)'
  const listeners = new Set<EventListenerOrEventListenerObject>()
  let width = 375
  vi.stubGlobal('innerWidth', width)
  const media = {
    get matches() {
      return width < 768
    },
    media: query,
    onchange: null,
    addEventListener: vi.fn(
      (_type: string, listener: EventListenerOrEventListenerObject) => listeners.add(listener),
    ),
    removeEventListener: vi.fn(
      (_type: string, listener: EventListenerOrEventListenerObject) => listeners.delete(listener),
    ),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
  } as unknown as MediaQueryList
  vi.stubGlobal('matchMedia', vi.fn(() => media))

  return {
    media,
    enterDesktop() {
      width = 1024
      vi.stubGlobal('innerWidth', width)
      const event = { matches: false, media: query } as MediaQueryListEvent
      for (const listener of listeners) {
        if (typeof listener === 'function') listener(event)
        else listener.handleEvent(event)
      }
    },
  }
}

const readHexToken = (css: string, name: string): string => {
  const value = css.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6});`, 'i'))?.[1]
  if (!value) throw new Error(`Token hexadécimal introuvable : --${name}`)
  return value
}

const relativeLuminance = (hex: string): number => {
  const channels = hex
    .slice(1)
    .match(/.{2}/g)
    ?.map((channel) => Number.parseInt(channel, 16))
  if (!channels || channels.length !== 3) throw new Error(`Couleur hexadécimale invalide : ${hex}`)

  const [red, green, blue] = channels.map((channel) => {
    const srgb = channel / 255
    return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue
}

const contrastRatio = (foreground: string, background: string): number => {
  const foregroundLuminance = relativeLuminance(foreground)
  const backgroundLuminance = relativeLuminance(background)
  const lighter = Math.max(foregroundLuminance, backgroundLuminance)
  const darker = Math.min(foregroundLuminance, backgroundLuminance)
  return (lighter + 0.05) / (darker + 0.05)
}

describe('fidélité à la refonte publique approuvée', () => {
  it('rend sur l’accueil le résumé compact des offres alimenté par l’API', async () => {
    const catalogue = {
      ...CATALOGUE,
      plans: CATALOGUE.plans.map((plan) =>
        plan.plan_code === 'essential'
          ? {
              ...plan,
              monthly_price: {
                chf: { amount_minor_units: 1234, currency: 'chf' as const },
                eur: { amount_minor_units: 1234, currency: 'eur' as const },
              },
            }
          : plan,
      ),
    }
    mockApi({ 'GET /billing/plans': { body: catalogue } })
    renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })

    const summary = await screen.findByRole('list', { name: 'Aperçu des offres Kivou' })
    expect(within(summary).getAllByRole('listitem')).toHaveLength(4)
    expect(within(summary).getByText(/12[,.]34/)).toBeInTheDocument()
    expect(within(summary).getByText('Essentiel')).toBeInTheDocument()
  })

  it('porte les choix visuels structurants de la référence publique', () => {
    const shell = read('src/layouts/PublicLayout.module.css')
    const landing = read('src/pages/Landing.module.css')

    expect(shell).toMatch(/--kivou-public-primary:\s*#173f33/)
    expect(shell).toMatch(/\.footer\s*\{[^}]*background:\s*var\(--kivou-bg-surface\)/s)
    expect(landing).toMatch(/\.h1\s*\{[^}]*font-family:\s*var\(--kivou-font-display\)/s)
    expect(landing).toMatch(/\.methodSection\s*\{[^}]*background:\s*var\(--kivou-public-primary\)/s)
  })
})

describe('fidélité au shell dashboard approuvé', () => {
  it('rend la sidebar et la topbar de la maquette sans donnée de démonstration', async () => {
    mockApi({
      'GET /signals': { body: { items: [], total: 0, limit: 20, offset: 0 } },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /target-icps': { body: [ICP] },
      'GET /notification-preferences': {
        body: {
          email_enabled: true,
          notification_email: 'claire@acme.test',
          updated_at: '2026-08-18T09:00:00+00:00',
        },
      },
    })
    renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })

    expect(await screen.findByText('Veille des marchés attribués')).toBeInTheDocument()
    expect(screen.getByText('Navigation')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Vue d’ensemble' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Vue d’ensemble' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(document.body).not.toHaveTextContent(/mode démonstration|compte démo|maquette de travail/i)
  })

  it('rend le rail clair et seulement les cinq destinations client approuvées', async () => {
    mockApi({
      'GET /signals': { body: feedPage([]) },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /target-icps': { body: [ICP] },
      'GET /notification-preferences': {
        body: {
          email_enabled: true,
          notification_email: 'claire@acme.test',
          updated_at: '2026-08-18T09:00:00+00:00',
        },
      },
    })
    renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })

    await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' })
    const navigation = document.querySelector<HTMLElement>('.sidebar-menu')
    expect(navigation).not.toBeNull()
    expect(within(navigation!).getAllByRole('link')).toHaveLength(5)
    const destinations = [
      ['Vue d’ensemble', '/app/dashboard'],
      ['Signaux', '/app/signals'],
      ['Entreprises', '/app/companies'],
      ['Profil de ciblage', '/app/icps'],
      ['Compte', '/app/settings'],
    ] as const
    for (const [name, href] of destinations) {
      expect(within(navigation!).getByRole('link', { name })).toHaveAttribute('href', href)
    }
    expect(within(navigation!).getByRole('link', { name: destinations[0][0] })).toHaveAttribute(
      'aria-current',
      'page',
    )
    for (const destination of ['Marchés', 'Veille', 'Notes', 'Apollo', 'Instantly']) {
      expect(
        within(navigation!).queryByRole('link', { name: new RegExp(destination, 'i') }),
      ).not.toBeInTheDocument()
    }

    const shell = read('src/layouts/AppShell.module.css')
    expect(shell).toMatch(
      /\.sidebar\s*\{[^}]*background:\s*var\(--kivou-connected-rail\)/s,
    )
    expect(shell).toMatch(
      /\.workspace\s*\{[^}]*background:\s*var\(--kivou-connected-canvas\)/s,
    )

    const tokens = read('src/styles/tokens.css')
    expect(tokens).toMatch(/--kivou-connected-rail:\s*#f3eee5;/)
    expect(tokens).toMatch(/--kivou-connected-canvas:\s*#f7f3ec;/)
    expect(
      contrastRatio(
        readHexToken(tokens, 'kivou-connected-muted'),
        readHexToken(tokens, 'kivou-connected-rail'),
      ),
    ).toBeGreaterThanOrEqual(4.5)
  })

  it.each([
    ['fr', 'Signaux', 'Détail du signal sélectionné'],
    ['en', 'Signals', 'Selected signal details'],
  ] as const)(
    'conserve le titre et les landmarks du workspace en %s',
    async (locale, title, detailLabel) => {
      mockApi({
        'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
        'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
        'GET /billing/status': { body: DISCOVERY_STATUS },
        'GET /target-icps': { body: [ICP] },
      })
      const session = {
        status: 'authenticated' as const,
        me: { ...ME, locale },
      }
      const { container } = renderApp(<AppRoutes />, {
        route: '/app/signals/sig_unlocked_1',
        session,
        locale,
      })

      expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument()
      expect(screen.getByRole('region', { name: detailLabel })).toBeInTheDocument()
      expect(container.querySelectorAll('main')).toHaveLength(1)
      expect(container.querySelectorAll('h1')).toHaveLength(1)
    },
  )

  it('nomme le drawer, y place le focus et expose son overlay', async () => {
    const user = userEvent.setup()
    stubMobileMedia()
    renderSignalsShell()
    await screen.findByRole('heading', { level: 1, name: 'Signaux' })

    const drawerToggle = screen.getByRole('button', { name: 'Ouvrir la navigation' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(drawerToggle)
    const drawer = screen.getByRole('dialog', { name: 'Navigation' })
    const close = within(drawer).getByRole('button', { name: 'Fermer' })
    expect(drawer).toContainElement(document.activeElement as HTMLElement)
    expect(document.querySelector('[data-slot="sheet-overlay"]')).not.toBeNull()

    await user.click(close)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(drawerToggle).toBeEnabled()
  })

  it('confine Tab et Maj+Tab aux contrôles du drawer', async () => {
    const user = userEvent.setup()
    stubMobileMedia()
    renderSignalsShell()
    await screen.findByRole('heading', { level: 1, name: 'Signaux' })
    await user.click(screen.getByRole('button', { name: 'Ouvrir la navigation' }))

    const drawer = screen.getByRole('dialog', { name: 'Navigation' })
    const first = within(drawer).getByRole('link', { name: 'Kivou, vue d’ensemble' })
    const last = within(drawer).getByRole('button', { name: 'Fermer' })

    last.focus()
    await user.tab()
    expect(first).toHaveFocus()
    await user.tab({ shift: true })
    expect(last).toHaveFocus()
  })

  it('ferme le drawer avec Échap', async () => {
    const user = userEvent.setup()
    stubMobileMedia()
    renderSignalsShell()
    await screen.findByRole('heading', { level: 1, name: 'Signaux' })
    const drawerToggle = screen.getByRole('button', { name: 'Ouvrir la navigation' })
    await user.click(drawerToggle)

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(drawerToggle).toBeEnabled()
  })

  it('distingue le scrim du bouton Fermer', async () => {
    const user = userEvent.setup()
    stubMobileMedia()
    renderSignalsShell()
    await screen.findByRole('heading', { level: 1, name: 'Signaux' })
    const drawerToggle = screen.getByRole('button', { name: 'Ouvrir la navigation' })
    await user.click(drawerToggle)

    const overlay = document.querySelector<HTMLElement>('[data-slot="sheet-overlay"]')
    expect(overlay).not.toBeNull()
    await user.click(overlay!)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(drawerToggle).toBeEnabled()
  })

  it('ferme le drawer quand une destination interne est choisie', async () => {
    const user = userEvent.setup()
    stubMobileMedia()
    renderSignalsShell()
    await screen.findByRole('heading', { level: 1, name: 'Signaux' })
    await user.click(screen.getByRole('button', { name: 'Ouvrir la navigation' }))

    const drawer = screen.getByRole('dialog', { name: 'Navigation' })
    await user.click(within(drawer).getByRole('link', { name: 'Entreprises' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('ferme le drawer au passage sur le rail desktop et libère son écouteur', async () => {
    const user = userEvent.setup()
    const desktop = stubMobileMedia()
    const { unmount } = renderSignalsShell()
    await screen.findByRole('heading', { level: 1, name: 'Signaux' })
    const drawerToggle = screen.getByRole('button', { name: 'Ouvrir la navigation' })
    await user.click(drawerToggle)

    act(() => desktop.enterDesktop())

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    unmount()
    expect(desktop.media.removeEventListener).toHaveBeenCalled()
  })

  it('garde un seul document sémantique de la liste au détail sélectionné', async () => {
    const user = userEvent.setup()
    const { container } = renderSignalsShell()

    await user.click(
      await screen.findByRole('link', {
        name: /^Constructions Bertrand SA — Réfection de la voirie communale/,
      }),
    )
    expect(
      await screen.findByRole('region', { name: 'Détail du signal sélectionné' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retour à la liste' })).toBeInTheDocument()
    expect(container.querySelectorAll('main')).toHaveLength(1)
    expect(container.querySelectorAll('h1')).toHaveLength(1)
  })

  it('porte les bascules CSS desktop et mobile sans simuler leurs mesures dans jsdom', () => {
    const shell = read('src/layouts/AppShell.module.css')
    const signals = read('src/pages/SignalsFeed.module.css')

    expect(shell).toMatch(/\.sidebar\s*\{[^}]*display:\s*none/s)
    expect(shell).not.toMatch(/\.topbar\s*\{[^}]*display:\s*none/s)
    expect(shell).toMatch(
      /\.topbar\s*\{[^}]*position:\s*absolute[^}]*width:\s*1px[^}]*height:\s*1px[^}]*overflow:\s*hidden[^}]*clip:/s,
    )
    expect(shell).toMatch(
      /@media \(min-width: 1024px\)\s*\{[\s\S]*?\.topbar\s*\{[^}]*position:\s*sticky[^}]*display:\s*flex[^}]*width:\s*auto[^}]*height:\s*auto[^}]*clip:\s*auto/s,
    )
    expect(shell).toMatch(
      /@media \(min-width: 1024px\)\s*\{[\s\S]*?\.mobileBar\s*\{[^}]*display:\s*none[\s\S]*?\.sidebar\s*\{[^}]*display:\s*flex/,
    )
    expect(signals).toMatch(
      /\.workspace\s*\{[^}]*grid-template-columns:\s*minmax\(16rem, 0\.82fr\) minmax\(0, 1\.48fr\)/s,
    )
    expect(signals).toMatch(
      /@media \(max-width: 899px\)\s*\{[\s\S]*?\.masterHidden,\s*\.detailHidden\s*\{[^}]*display:\s*none/,
    )
  })
})
