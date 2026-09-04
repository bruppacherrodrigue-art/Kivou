import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AppRoutes } from '../App'
import { CATALOGUE, mockApi, renderApp } from '../test/harness'

describe('contenu et agencement exacts de la référence publique', () => {
  it('présente les quatre niveaux de analyse du signal', () => {
    mockApi({})
    const view = renderApp(<AppRoutes />, { route: '/' })
    const title = screen.getByRole('heading', { level: 2, name: 'Voici ce que vous voyez lorsqu’un signal remonte.' })
    const section = title.closest('section')!
    const steps = section.querySelectorAll('.signal-path-step')
    expect(steps).toHaveLength(4)
    for (const heading of ['Fait publié', 'Pertinence expliquée', 'Inconnues visibles', 'Votre apprentissage']) {
      expect(within(section).getByText(heading)).toBeInTheDocument()
    }
    view.unmount()
  })

  it('sépare les questions entreprise, marché, analyse et calendrier', () => {
    mockApi({})
    const view = renderApp(<AppRoutes />, { route: '/' })
    const title = screen.getByRole('heading', { level: 2, name: 'Les questions auxquelles un signal doit répondre.' })
    const section = title.closest('section')!
    for (const heading of ['Qui a gagné ?', 'Que doit-elle exécuter ?', 'Où votre offre peut-elle être utile ?', 'Quand examiner le compte ?']) {
      expect(within(section).getByRole('heading', { level: 3, name: heading })).toBeInTheDocument()
    }
    view.unmount()
  })

  it('relie les pages dédiées prévues par la source', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    renderApp(<AppRoutes />, { route: '/' })
    expect(screen.getByRole('link', { name: 'Voir l’exemple complet' })).toHaveAttribute('href', '/exemple-de-signal')
    expect(screen.getByRole('link', { name: 'Voir la méthode' })).toHaveAttribute('href', '/produit')
    expect(screen.getByRole('link', { name: 'Comparer les offres' })).toHaveAttribute('href', '/tarifs')
    await screen.findByText('CHF 49')
  })

  it('rend la page produit complète dans les classes de la référence', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    const { container } = renderApp(<AppRoutes />, { route: '/produit' })
    expect(screen.getByRole('heading', { level: 1, name: 'Kivou suit ce qui se passe une fois le marché attribué.' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Cinq étapes, du profil cible au signal.' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Des faits publiés à l’angle commercial à vérifier.' })).toBeInTheDocument()
    expect(container.querySelector('.pipeline-card .pipeline')).not.toBeNull()
    expect(container.querySelector('.fact-module .analysis-bridge')).not.toBeNull()
    expect(container).toHaveTextContent('H. Hüther GmbH')
    expect(container).toHaveTextContent('Source TED disponible pour contrôle')
    await screen.findByRole('link', { name: 'Configurer mon profil' })
  })
})
