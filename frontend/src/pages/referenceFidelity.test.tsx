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
  mockApi,
  renderApp,
  UNAUTHENTICATED,
} from '../test/harness'

const read = (path: string) => readFileSync(join(process.cwd(), path), 'utf8')

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

  it('porte la géométrie et les couleurs du shell de référence', () => {
    const shell = read('src/layouts/AppShell.module.css')
    expect(shell).toMatch(/\.topbar\s*\{/)
    expect(shell).toMatch(/\.sidebar\s*\{[^}]*background:\s*var\(--kivou-sidebar-bg\)/s)
    expect(shell).toMatch(/\.navItemActive\s*\{[^}]*background:\s*rgba\(255,\s*255,\s*255,\s*0\.1\)/s)
  })
})
