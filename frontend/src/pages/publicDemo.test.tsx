import { screen } from '@testing-library/react'
import { useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { CATALOGUE, UNAUTHENTICATED, mockApi, renderApp } from '../test/harness'

function LocationProbe() {
  const location = useLocation()
  return <span data-testid="current-path">{location.pathname}</span>
}

describe('page Exemple de signal masquée', () => {
  it('redirige une ancienne adresse vers le fonctionnement sans afficher la démo', async () => {
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    renderApp(<><AppRoutes /><LocationProbe /></>, {
      route: '/exemple-de-signal',
      session: UNAUTHENTICATED,
    })

    expect(await screen.findByRole('heading', {
      level: 1,
      name: 'Kivou suit ce qui se passe une fois le marché attribué.',
    })).toBeInTheDocument()
    expect(screen.getByTestId('current-path')).toHaveTextContent('/produit')
    expect(screen.queryByRole('heading', {
      level: 1,
      name: 'H. Hüther GmbH a remporté un marché de 5,22 M€ à Munich.',
    })).not.toBeInTheDocument()
    scrollTo.mockRestore()
  })

  it.each(['/', '/produit', '/tarifs', '/contact', '/informations-legales'])(
    'ne propose aucun accès à la démo depuis %s, menus mobile et footer compris',
    (route) => {
      mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
      const view = renderApp(<AppRoutes />, { route, session: UNAUTHENTICATED })

      expect(view.container.querySelector('a[href*="exemple-de-signal"]')).toBeNull()
      expect(screen.queryByText('Exemple de signal')).not.toBeInTheDocument()
      view.unmount()
    },
  )
})
