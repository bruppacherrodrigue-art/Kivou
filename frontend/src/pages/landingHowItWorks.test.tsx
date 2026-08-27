import { describe, expect, it, vi, afterEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AppRoutes } from '../App'
import { publicDemoSignal } from '../content/publicDemoSignal'
import { CATALOGUE, mockApi, renderApp } from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

describe('section Comment ça marche de la page d’accueil', () => {
  it('présente un parcours court du ciblage à l’apprentissage client', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    const { container } = renderApp(<AppRoutes />, { route: '/' })

    const section = await screen.findByRole('heading', {
      level: 2,
      name: 'Kivou transforme les attributions publiques en prospects à examiner selon leur calendrier.',
    })
    expect(section.closest('section')).toHaveAttribute('id', 'comment')

    const text = container.textContent ?? ''
    for (const marker of [
      'SURVEILLANCE COMMERCIALE CONTINUE',
      'Votre profil de ciblage',
      'Votre offre',
      'Vos prospects',
      'Votre territoire',
      'Vos priorités',
      'Votre flux de signaux personnalisés',
      'Du signal à votre apprentissage',
      'DANS VOTRE DASHBOARD',
      'Un chemin de lecture clair, jusqu’à votre note.',
    ]) {
      expect(text).toContain(marker)
    }

    expect(text).not.toContain('De l’attribution publique à l’action commerciale')
    expect(text).not.toContain('Une attribution publique n’est pas encore une occasion commerciale')
    expect(text).not.toContain('Coordonnées professionnelles')
    expect(text).not.toContain('Action recommandée')
  })

  it('présente quatre étapes et termine par l’avis et la note du client', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })
    await screen.findByRole('heading', { level: 2, name: /Kivou transforme/ })

    const process = screen.getByRole('list', { name: 'Du signal à votre apprentissage' })
    const steps = within(process).getAllByRole('listitem')

    expect(steps).toHaveLength(4)
    expect(within(steps[0]).getByText('01')).toBeInTheDocument()
    expect(within(steps[0]).getByRole('heading', { level: 4, name: 'Fait publié' })).toBeInTheDocument()
    expect(within(steps[3]).getByText('04')).toBeInTheDocument()
    expect(within(steps[3]).getByRole('heading', { level: 4, name: 'Votre apprentissage' })).toBeInTheDocument()
    expect(steps[3].className).toMatch(/final/i)
  })

  it('ne dépend plus d’une capture statique de l’ancien dashboard', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })
    await screen.findByRole('heading', { level: 2, name: /Kivou transforme/ })

    expect(screen.queryByRole('img', { name: /Tableau de bord Kivou/i })).not.toBeInTheDocument()
    expect(screen.queryByText('Du fait publié à votre avis — sans confondre preuve, analyse et apprentissage.')).not.toBeInTheDocument()
  })

  it('rend visibles les cinq repères du parcours et ses deux actions utiles', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })
    await screen.findByRole('heading', { level: 2, name: /Kivou transforme/ })

    const dashboardSection = screen
      .getByRole('heading', { level: 3, name: 'Un chemin de lecture clair, jusqu’à votre note.' })
      .closest('section')!
    for (const label of [
      'Faits publiés',
      'Périmètre concret',
      'Analyse Kivou',
      'Preuve officielle',
      'Votre avis et votre note',
    ]) {
      expect(within(dashboardSection).getByText(label)).toBeInTheDocument()
    }

    expect(screen.getByRole('link', { name: 'Voir un signal complet' })).toHaveAttribute(
      'href',
      '/exemple-de-signal',
    )
    expect(screen.getAllByRole('link', { name: 'Recevoir mes 3 signaux' })[0]).toHaveAttribute(
      'href',
      '/signup',
    )
    expect(screen.queryByRole('link', { name: 'Comparer les offres' })).not.toBeInTheDocument()
  })

  it('reste entièrement localisée en anglais sans réintroduire l’ancien parcours', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/', locale: 'en' })

    expect(
      await screen.findByRole('heading', {
        level: 2,
        name: 'Kivou turns public contract awards into prospects to assess against their published schedule.',
      }),
    ).toBeInTheDocument()
    expect(container.textContent).toContain('CONTINUOUS SALES MONITORING')
    expect(container.textContent).toContain('Target profile')
    expect(container.textContent).toContain('From signal to learning')
    expect(container.textContent).toContain('Published facts')
    expect(container.textContent).toContain('Your view and note')
    expect(container.textContent).not.toContain('Verified company details')
    expect(container.textContent).not.toContain('SURVEILLANCE COMMERCIALE CONTINUE')
    expect(screen.queryByRole('img', { name: /Kivou dashboard/i })).not.toBeInTheDocument()
  })

  it('conserve les ancres comment et tarifs', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    renderApp(<AppRoutes />, { route: '/' })
    const user = userEvent.setup()

    await user.click((await screen.findAllByRole('link', { name: 'Tarifs' }))[0])

    await waitFor(() => expect(document.activeElement?.id).toBe('tarifs'))
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: 'Choisissez la couverture commerciale adaptée à vos objectifs',
      }),
    ).toBeInTheDocument()
  })

  it('met les quatre offres complètes et leurs prix au premier plan', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    renderApp(<AppRoutes />, { route: '/' })

    const title = await screen.findByRole('heading', {
      level: 2,
      name: 'Choisissez la couverture commerciale adaptée à vos objectifs',
    })
    const section = title.closest('section')!

    expect(within(section).getAllByRole('article')).toHaveLength(4)

    const expectedPlans = [
      ['Découverte', 'Gratuit', 'Validez la pertinence de Kivou avec vos trois premiers signaux.'],
      ['Essential', '49', 'Concentrez votre prospection sur une priorité commerciale.'],
      ['Pro', '99', 'Suivez plusieurs priorités et agissez avec le contexte et les preuves utiles.'],
      ['Scale', '199', 'Étendez votre couverture à davantage de marchés et de territoires.'],
    ] as const

    for (const [name, price, positioning] of expectedPlans) {
      const card = within(section).getByRole('heading', { level: 3, name }).closest('article')!
      expect(card).toHaveTextContent(price)
      expect(card).toHaveTextContent(positioning)
      expect(within(card).getByText('Ce qui est inclus')).toBeInTheDocument()
      expect(within(card).getByRole('link')).toHaveAttribute('href', '/signup')
    }

    expect(section).not.toHaveTextContent('D’abord le ciblage, ensuite les signaux')
    expect(section).not.toHaveTextContent('Trois signaux complets')
    expect(section).not.toHaveTextContent('Compte sans carte bancaire')
  })

  it('n’invente aucun prix quand le catalogue est indisponible', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })

    await screen.findByRole('heading', {
      level: 2,
      name: 'Choisissez la couverture commerciale adaptée à vos objectifs',
    })

    expect(screen.getByText('Les tarifs sont momentanément indisponibles. La création de compte reste ouverte.')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/CHF\s?49|CHF\s?99|CHF\s?199/)
  })
})

describe('informations publiques de la démonstration', () => {
  it('utilise uniquement les coordonnées publiques vérifiées de H. Hüther GmbH', () => {
    expect(publicDemoSignal.winner).toMatchObject({
      legalName: 'H. Hüther GmbH',
      address: 'Graseweg 8, 34346 Hedemünden',
      website: 'https://huether-gmbh.de',
      phone: '+49 5545 9606-0',
      identifier: { value: 'DE115302781' },
      contactVerifiedAt: '2026-08-22',
      contactVerificationSource: 'https://huether-gmbh.de/impressum-huther-objektturen/',
    })

    expect(JSON.stringify(publicDemoSignal.winner).toLowerCase()).not.toContain('email')
    expect(JSON.stringify(publicDemoSignal.winner).toLowerCase()).not.toContain('geschäftsführer')
  })
})
