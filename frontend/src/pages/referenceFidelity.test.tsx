import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  feedPage,
  mockApi,
  renderApp,
  UNAUTHENTICATED,
} from '../test/harness'

const read = (path: string) => readFileSync(join(process.cwd(), path), 'utf8')

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

    const navigation = await screen.findByRole('navigation', { name: 'Navigation principale' })
    expect(within(navigation).getAllByRole('link')).toHaveLength(5)
    const destinations = [
      ['Vue d’ensemble', '/app/dashboard'],
      ['Signaux', '/app/signals'],
      ['Entreprises', '/app/companies'],
      ['Profil de ciblage', '/app/icps'],
      ['Compte', '/app/settings'],
    ] as const
    for (const [name, href] of destinations) {
      expect(within(navigation).getByRole('link', { name })).toHaveAttribute('href', href)
    }
    expect(within(navigation).getByRole('link', { name: destinations[0][0] })).toHaveAttribute(
      'aria-current',
      'page',
    )
    for (const destination of ['Marchés', 'Veille', 'Notes', 'Apollo', 'Instantly']) {
      expect(
        within(navigation).queryByRole('link', { name: new RegExp(destination, 'i') }),
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
})
