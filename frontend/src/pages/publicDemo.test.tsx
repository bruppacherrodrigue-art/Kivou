import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AppRoutes } from '../App'
import { CATALOGUE, UNAUTHENTICATED, mockApi, recordedCalls, renderApp } from '../test/harness'

const TED = 'https://ted.europa.eu/en/notice/568562-2026/xml'

describe('exemple de signal exact de la référence publique', () => {
  it('se rend sans session et ne lit que le catalogue public nécessaire au CTA', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    renderApp(<AppRoutes />, { route: '/exemple-de-signal', session: UNAUTHENTICATED })

    expect(screen.getByRole('heading', { level: 1, name: 'H. Hüther GmbH a remporté un marché de 5,22 M€ à Munich.' })).toBeInTheDocument()
    await screen.findByRole('link', { name: 'Commencer gratuitement' })
    expect(recordedCalls.map((call) => `${call.method} ${call.url}`)).toEqual(['GET /billing/plans'])
  })

  it('conserve le h1, les modules et la hiérarchie de classes de la source', () => {
    mockApi({})
    const view = renderApp(<AppRoutes />, { route: '/exemple-de-signal', session: UNAUTHENTICATED })
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(document.querySelector('.page-hero .hero-grid .signal-card')).not.toBeNull()
    expect(document.querySelector('.data-grid .data-card')).not.toBeNull()
    expect(document.querySelector('.opportunity-panel .opportunity-rows')).not.toBeNull()
    expect(document.querySelector('.fit-panel .fit-list')).not.toBeNull()
    expect(document.querySelector('.evidence-grid .evidence-card')).not.toBeNull()
    view.unmount()
  })

  it('affiche les faits, volumes, source officielle et limite exacts', () => {
    mockApi({})
    const view = renderApp(<AppRoutes />, { route: '/exemple-de-signal', session: UNAUTHENTICATED })
    const facts = screen.getByRole('heading', { name: 'Ce que l’avis TED indique.' }).closest('section')!
    for (const value of ['H. Hüther GmbH', '5 219 043,35 EUR', '26-000.723.722', '45420000', '80335 München']) {
      expect(within(facts).getAllByText(value).length).toBeGreaterThan(0)
    }
    for (const value of ['497', '234', '5 485 m', '425 m²', '24', '13']) {
      expect(within(facts).getByText(value)).toBeInTheDocument()
    }
    for (const link of screen.getAllByRole('link', { name: /Ouvrir l’avis.*TED/i })) {
      expect(link).toHaveAttribute('href', TED)
      expect(link).toHaveAttribute('target', '_blank')
      expect(link.getAttribute('rel')).toContain('noreferrer')
    }
    expect(screen.getByText(/Kivou n’a pas accès au cahier des charges/)).toBeInTheDocument()
    view.unmount()
  })

  it('conserve les CTA sur la même origine et retire la promesse hebdomadaire absente du catalogue', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    const { container } = renderApp(<AppRoutes />, { route: '/exemple-de-signal', session: UNAUTHENTICATED })
    expect(await screen.findByRole('link', { name: 'Commencer gratuitement' })).toHaveAttribute('href', '/signup?plan=discovery')
    expect(screen.getByRole('link', { name: 'Voir les tarifs' })).toHaveAttribute('href', '/tarifs')
    expect(container).toHaveTextContent('Les trois premiers sont accessibles dès l’inscription, sans alerte récurrente.')
    expect(container).not.toHaveTextContent(/un nouveau signal.*semaine/i)
  })
})
