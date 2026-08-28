import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AppRoutes } from '../App'
import { CATALOGUE, mockApi, renderApp } from '../test/harness'

describe('contenu et agencement de la refonte publique', () => {
  it('présente la lecture du signal en quatre niveaux explicites', () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })
    const title = screen.getByRole('heading', { level: 2, name: 'Voici ce que vous voyez lorsqu’un signal remonte.' })
    const section = title.closest('section')!
    const steps = within(section).getAllByRole('listitem')
    expect(steps).toHaveLength(4)
    for (const heading of ['Fait publié', 'Pertinence expliquée', 'Inconnues visibles', 'Votre apprentissage']) {
      expect(within(section).getByRole('heading', { level: 3, name: heading })).toBeInTheDocument()
    }
  })

  it('sépare les questions entreprise, marché, analyse et calendrier', () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })
    const title = screen.getByRole('heading', { level: 2, name: 'Les questions auxquelles un signal doit répondre.' })
    const section = title.closest('section')!
    for (const heading of ['Qui a gagné ?', 'Que doit-elle exécuter ?', 'Où votre offre peut-elle être utile ?', 'Quand examiner le compte ?']) {
      expect(within(section).getByRole('heading', { level: 3, name: heading })).toBeInTheDocument()
    }
  })

  it('conserve les ancres historiques tout en reliant les nouvelles pages dédiées', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    renderApp(<AppRoutes />, { route: '/' })
    expect(document.getElementById('comment')).toHaveAttribute('tabindex', '-1')
    expect(document.getElementById('tarifs')).toHaveAttribute('tabindex', '-1')
    expect(screen.getByRole('link', { name: 'Voir la méthode' })).toHaveAttribute('href', '/produit')
    expect(screen.getByRole('link', { name: 'Comparer les offres' })).toHaveAttribute('href', '/tarifs')
  })

  it('rend la page produit complète et localisée', () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/produit' })
    expect(screen.getByRole('heading', { level: 1, name: 'Kivou suit ce qui se passe après l’attribution.' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Cinq étapes, du ciblage au signal.' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Des faits publiés à l’angle commercial à vérifier.' })).toBeInTheDocument()
    expect(container).toHaveTextContent('H. Hüther GmbH')
    expect(container).toHaveTextContent('Source TED disponible pour contrôle')
  })
})
