import { describe, expect, it, vi, afterEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { readFileSync } from 'node:fs'

import { AppRoutes } from '../App'
import type { PlanCatalogue } from '../api/types'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

function publicCatalogue(overrides?: Partial<Record<'discovery' | 'essential' | 'pro' | 'scale', object>>): PlanCatalogue {
  return {
    ...CATALOGUE,
    plans: CATALOGUE.plans.map((plan) => ({
      ...plan,
      entitlements: { ...plan.entitlements },
      ...(overrides?.[plan.plan_code] ?? {}),
    })),
  }
}

function renderLanding(catalogue: PlanCatalogue = CATALOGUE, locale: 'fr' | 'en' = 'fr') {
  mockApi({ 'GET /billing/plans': { body: catalogue } })
  return renderApp(<AppRoutes />, { route: '/', locale })
}

describe('tarifs publics — valeur avant contraintes', () => {
  it('rend les quatre offres et leurs montants exclusivement depuis le catalogue API', async () => {
    const catalogue = publicCatalogue({
      essential: {
        monthly_price: {
          chf: { amount_minor_units: 1234, currency: 'chf' },
          eur: { amount_minor_units: 1234, currency: 'eur' },
        },
      },
    })
    renderLanding(catalogue)

    const title = await screen.findByRole('heading', {
      level: 2,
      name: 'Choisissez la couverture commerciale adaptée à vos objectifs',
    })
    const section = title.closest('section')!

    expect(within(section).getAllByRole('article')).toHaveLength(4)
    expect(within(section).getByText('4 offres · Facturation mensuelle')).toBeInTheDocument()
    expect(
      within(section).getByText(
        'Commencez par trois signaux réels. Étendez ensuite votre couverture et votre capacité de suivi à mesure que votre prospection se développe.',
      ),
    ).toBeInTheDocument()

    const essential = within(section)
      .getByRole('heading', { level: 3, name: 'Essential' })
      .closest('article')!
    expect(essential.textContent).toMatch(/12[,.]34/)
    expect(essential).not.toHaveTextContent(/(^|\D)49([,.\s]|$)/)
  })

  it('ne contient aucun prix de production dans le JSX ou les dictionnaires', () => {
    const sources = [
      '../billing/PlanGrid.tsx',
      './Landing.tsx',
      '../i18n/fr.ts',
      '../i18n/en.ts',
    ].map((path) => readFileSync(new URL(path, import.meta.url), 'utf8'))

    for (const source of sources) {
      expect(source).not.toMatch(/(?:CHF|EUR|€)\s*(?:49|99|199)\b/)
      expect(source).not.toMatch(/amount_minor_units\s*:\s*(?:4900|9900|19900)\b/)
    }
  })

  it('place la promesse commerciale avant le prix puis les capacités dans chaque carte publique', async () => {
    renderLanding()

    const promise = await screen.findByText(
      'Suivez plusieurs priorités et agissez avec le contexte et les preuves utiles.',
    )
    const card = promise.closest('article')!
    const price = within(card).getByText(/99/)
    const included = within(card).getByText('Ce qui est inclus')

    expect(promise.compareDocumentPosition(price) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(price.compareDocumentPosition(included) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('suit exclusivement recommended fourni par l’API', async () => {
    renderLanding(
      publicCatalogue({
        essential: { recommended: true },
        pro: { recommended: false },
      }),
    )

    const ribbon = await screen.findByText('Recommandé')
    const recommendedCard = ribbon.closest('article')!
    expect(within(recommendedCard).getByRole('heading', { name: 'Essential' })).toBeInTheDocument()
    expect(screen.getAllByText('Recommandé')).toHaveLength(1)
    expect(
      within(screen.getByRole('heading', { name: 'Pro' }).closest('article')!).queryByText(
        'Recommandé',
      ),
    ).not.toBeInTheDocument()
  })

  it('affiche des CTA honnêtes et uniquement des capacités réellement exerçables', async () => {
    const catalogue = publicCatalogue()
    catalogue.plans = catalogue.plans.map((plan) =>
      plan.plan_code === 'essential'
        ? {
            ...plan,
            entitlements: {
              ...plan.entitlements,
              max_territories_per_icp: 7,
              territory_mode: 'single',
            },
          }
        : plan,
    )
    renderLanding(catalogue)

    expect(
      await screen.findByRole('link', { name: 'Voir mes 3 premiers signaux' }),
    ).toHaveAttribute('href', '/signup')
    expect(screen.getAllByRole('link', { name: 'Créer mon compte' })).toHaveLength(3)
    expect(screen.queryByRole('link', { name: /Choisir (Essential|Pro|Scale)/ })).not.toBeInTheDocument()
    expect(screen.getByText('Jusqu’à 7 territoires par profil')).toBeInTheDocument()
    expect(screen.getByText('Plusieurs territoires par profil')).toBeInTheDocument()
    expect(screen.getByText('Couverture territoriale étendue')).toBeInTheDocument()

    const page = document.body.textContent ?? ''
    for (const forbidden of [
      'Founding',
      'Fondateur',
      'Export limité',
      'Export étendu',
      'Filtres de base',
      'Filtres avancés',
      'Recherche de décideur',
      'Intégration CRM',
      'Temps réel',
    ]) {
      expect(page).not.toContain(forbidden)
    }
    expect(page).toContain('Alertes e-mail hebdomadaires')
    expect(page).toContain('Alertes e-mail quotidiennes')
    expect(page).toContain('Alertes e-mail prioritaires')
  })

  it('applique la même hiérarchie et le même niveau de vérité en anglais', async () => {
    renderLanding(CATALOGUE, 'en')

    const title = await screen.findByRole('heading', {
      level: 2,
      name: 'Choose the sales coverage that fits your goals',
    })
    const section = title.closest('section')!
    expect(within(section).getByText('4 plans · Monthly billing')).toBeInTheDocument()
    expect(
      within(section).getByText(
        'Start with three real signals. Then expand your coverage and tracking capacity as your prospecting grows.',
      ),
    ).toBeInTheDocument()
    expect(within(section).getByText('Validate Kivou’s relevance with your first three signals.')).toBeInTheDocument()
    expect(within(section).getByText('Focus your prospecting on one sales priority.')).toBeInTheDocument()
    expect(
      within(section).getByText(
        'Track several priorities and act with the context and evidence you need.',
      ),
    ).toBeInTheDocument()
    expect(
      within(section).getByText('Expand your coverage across more markets and territories.'),
    ).toBeInTheDocument()
    expect(within(section).getByRole('link', { name: 'See my first 3 signals' })).toHaveAttribute(
      'href',
      '/signup',
    )
    expect(within(section).getAllByRole('link', { name: 'Create my account' })).toHaveLength(3)
  })

  it('conserve l’ancre tarifs et son état explicite quand le catalogue échoue', async () => {
    mockApi({
      'GET /billing/plans': { status: 503, body: { detail: { code: 'billing_unavailable' } } },
    })
    renderApp(<AppRoutes />, { route: '/#tarifs' })

    const section = document.getElementById('tarifs')
    await waitFor(() => expect(section).toBeInTheDocument())
    expect(section).toHaveAttribute('tabindex', '-1')
    expect(
      screen.getByText('Les tarifs sont momentanément indisponibles. La création de compte reste ouverte.'),
    ).toBeInTheDocument()
  })
})

describe('séparation avec la facturation connectée', () => {
  it('préserve les actions serveur et les libellés de choix dans /app/billing', async () => {
    mockApi({
      'GET /billing/plans': { body: CATALOGUE },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })

    expect(await screen.findByRole('button', { name: 'Choisir Essential' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choisir Pro' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choisir Scale' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Créer mon compte' })).not.toBeInTheDocument()
  })
})
