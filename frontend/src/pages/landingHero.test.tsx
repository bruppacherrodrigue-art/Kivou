import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AppRoutes } from '../App'
import { CATALOGUE, mockApi, renderApp, UNAUTHENTICATED } from '../test/harness'

describe('hero exact de la référence publique', () => {
  it('porte la promesse, ses CTA et le signal de référence', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })

    expect(screen.getByRole('heading', { level: 1, name: 'Repérez les entreprises qui viennent de gagner un marché public.' })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(screen.getByText('Veille des marchés attribués')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'Voir mes 3 premiers signaux' })).toHaveAttribute('href', '/signup?plan=discovery')
    expect(screen.getByRole('link', { name: 'Examiner un signal complet' })).toHaveAttribute('href', '/exemple-de-signal')
    expect(screen.getByText(/3 signaux gratuits · Sans carte bancaire/)).toBeInTheDocument()

    const signal = screen.getByText('H. Hüther GmbH').closest('article')!
    expect(within(signal).getByText('H. Hüther GmbH')).toBeInTheDocument()
    expect(within(signal).getByText('5,22 M€')).toBeInTheDocument()
    expect(within(signal).getByText('TED 568562-2026')).toBeInTheDocument()
  })

  it('expose le menu public complet avec les routes de la référence', () => {
    mockApi({})
    const view = renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
    const nav = screen.getByRole('navigation', { name: 'Navigation principale' })
    for (const [name, href] of [
      ['Accueil', '/'], ['Comment ça marche', '/produit'], ['Exemple de signal', '/exemple-de-signal'], ['Tarifs', '/tarifs'], ['Contact', '/contact'],
    ] as const) {
      expect(within(nav).getAllByRole('link', { name })[0]).toHaveAttribute('href', href)
    }
    view.unmount()
  })

  it('reste la source française exacte même avec initialLocale="en"', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    const { container } = renderApp(<AppRoutes />, {
      route: '/',
      locale: 'en',
      session: UNAUTHENTICATED,
    })
    expect(screen.getByRole('heading', { level: 1, name: 'Repérez les entreprises qui viennent de gagner un marché public.' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'Voir mes 3 premiers signaux' })).toHaveAttribute('href', '/signup?plan=discovery')
    expect(container).not.toHaveTextContent('Spot companies')
    expect(document.documentElement.lang).toBe('fr')
  })
})
