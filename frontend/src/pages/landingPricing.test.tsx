import { readFileSync } from 'node:fs'
import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AppRoutes } from '../App'
import type { PlanCatalogue } from '../api/types'
import { AUTHENTICATED, CATALOGUE, DISCOVERY_STATUS, mockApi, renderApp } from '../test/harness'

function catalogueWithEssentialPrice(amount: number): PlanCatalogue {
  return {
    ...CATALOGUE,
    plans: CATALOGUE.plans.map((plan) => plan.plan_code === 'essential'
      ? { ...plan, monthly_price: { chf: { amount_minor_units: amount, currency: 'chf' }, eur: { amount_minor_units: amount, currency: 'eur' } } }
      : plan),
  }
}

describe('tarifs publics de la refonte', () => {
  it('rend les offres et montants exclusivement depuis le catalogue API', async () => {
    mockApi({ 'GET /billing/plans': { body: catalogueWithEssentialPrice(1234) } })
    renderApp(<AppRoutes />, { route: '/tarifs' })
    const title = screen.getByRole('heading', { level: 1, name: 'Choisissez la couverture adaptée à votre prospection.' })
    expect(title).toBeInTheDocument()
    const grid = (await screen.findByRole('heading', { level: 3, name: 'Essential' })).closest('ul')!
    expect(within(grid).getAllByRole('article')).toHaveLength(4)
    const essential = within(grid).getByRole('heading', { level: 3, name: 'Essential' }).closest('article')!
    expect(essential.textContent).toMatch(/12[,.]34/)
    expect(within(essential).getByRole('link')).toHaveAttribute('href', '/signup?plan=essential')
  })

  it('n’écrit aucun prix de production dans les composants marketing', () => {
    const sources = ['../billing/PlanGrid.tsx', './Landing.tsx', './PublicPricing.tsx', '../content/marketingCopy.ts']
      .map((path) => readFileSync(new URL(path, import.meta.url), 'utf8'))
    for (const source of sources) {
      expect(source).not.toMatch(/(?:CHF|EUR|€)\s*(?:49|99|199)\b/)
      expect(source).not.toMatch(/amount_minor_units\s*:\s*(?:4900|9900|19900)\b/)
    }
  })

  it('suit exclusivement le plan recommandé fourni par l’API', async () => {
    const catalogue = { ...CATALOGUE, plans: CATALOGUE.plans.map((plan) => ({ ...plan, recommended: plan.plan_code === 'essential' })) }
    mockApi({ 'GET /billing/plans': { body: catalogue } })
    renderApp(<AppRoutes />, { route: '/tarifs' })
    const ribbon = await screen.findByText('Recommandé')
    expect(within(ribbon.closest('article')!).getByRole('heading', { name: 'Essential' })).toBeInTheDocument()
    expect(screen.getAllByText('Recommandé')).toHaveLength(1)
  })

  it('affiche un état honnête quand le catalogue échoue', async () => {
    mockApi({ 'GET /billing/plans': { status: 503, body: { detail: { code: 'billing_unavailable' } } } })
    renderApp(<AppRoutes />, { route: '/tarifs' })
    expect(await screen.findByText(/Les tarifs sont momentanément indisponibles/)).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/CHF\s?49|CHF\s?99|CHF\s?199/)
  })

  it('préserve les actions de facturation serveur dans le dashboard', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE }, 'GET /billing/status': { body: DISCOVERY_STATUS } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })
    expect(await screen.findByRole('button', { name: 'Choisir Essential' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choisir Pro' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choisir Scale' })).toBeInTheDocument()
  })
})
