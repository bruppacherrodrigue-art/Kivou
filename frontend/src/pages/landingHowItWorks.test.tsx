import { describe, expect, it, vi, afterEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AppRoutes } from '../App'
import { publicDemoSignal } from '../content/publicDemoSignal'
import { CATALOGUE, mockApi, renderApp } from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

describe('section Comment ça marche de la page d’accueil', () => {
  it('remplace les cinq cartes abstraites par une démonstration complète de la machine Kivou', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    const { container } = renderApp(<AppRoutes />, { route: '/' })

    const section = await screen.findByRole('heading', {
      level: 2,
      name: 'Kivou transforme les marchés récemment attribués en prospects que vous pouvez contacter au bon moment.',
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
      'De l’attribution publique à l’action commerciale',
      'DANS VOTRE DASHBOARD',
      'Une attribution publique n’est pas encore une occasion commerciale',
      'Une analyse commerciale que vous pouvez vérifier',
      'Votre prochain prospect a peut-être remporté un contrat cette semaine',
    ]) {
      expect(text).toContain(marker)
    }

    expect(text).not.toContain('Ce que Kivou affirme, et ce qu’il qualifie')
    expect(text).not.toContain('Chaque signal répond aux questions de votre équipe commerciale')
    expect(text).not.toMatch(/confiance réduite/i)
  })

  it('présente six étapes orientées valeur avec une dernière étape commerciale', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })
    await screen.findByRole('heading', { level: 2, name: /Kivou transforme/ })

    const process = screen.getByRole('list', { name: 'De l’attribution publique à l’action commerciale' })
    const steps = within(process).getAllByRole('listitem')

    expect(steps).toHaveLength(6)
    expect(within(steps[0]).getByText('01')).toBeInTheDocument()
    expect(within(steps[0]).getByRole('heading', { level: 4, name: 'Kivou surveille' })).toBeInTheDocument()
    expect(within(steps[5]).getByText('06')).toBeInTheDocument()
    expect(within(steps[5]).getByRole('heading', { level: 4, name: 'Votre équipe agit' })).toBeInTheDocument()
    expect(steps[5].className).toMatch(/final/i)
  })

  it('intègre une capture responsive du dashboard avec un texte alternatif utile et des dimensions stables', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })

    const image = await screen.findByRole('img', {
      name: /Tableau de bord Kivou montrant un signal commercial pour une entreprise récemment gagnante/i,
    })

    expect(image).toHaveAttribute('src', '/demo/kivou-dashboard-fr-desktop.webp')
    expect(image).toHaveAttribute('width', '1600')
    expect(image).toHaveAttribute('height', '1080')
    expect(image).toHaveAttribute('loading', 'lazy')
    expect(image).not.toHaveAttribute('fetchpriority', 'high')

    const picture = image.closest('picture')!
    expect(picture.querySelector('source[media="(max-width: 767px)"]')).toHaveAttribute(
      'srcset',
      '/demo/kivou-dashboard-fr-mobile.webp',
    )
  })

  it('rend visibles les repères commerciaux autour de la capture et les CTA attendus', async () => {
    mockApi({})
    renderApp(<AppRoutes />, { route: '/' })
    await screen.findByRole('heading', { level: 2, name: /Kivou transforme/ })

    for (const label of [
      'Entreprise identifiée',
      'Coordonnées professionnelles',
      'Timing qualifié',
      'Action recommandée',
      'Preuve officielle',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }

    expect(screen.getByRole('link', { name: 'Voir un signal complet' })).toHaveAttribute(
      'href',
      '/exemple-de-signal',
    )
    expect(screen.getAllByRole('link', { name: 'Recevoir mes 3 signaux' })[0]).toHaveAttribute(
      'href',
      '/signup',
    )
    expect(screen.getByRole('link', { name: 'Voir mes 3 premiers signaux' })).toHaveAttribute(
      'href',
      '/signup',
    )
    expect(screen.getByRole('link', { name: 'Comparer les offres' })).toHaveAttribute('href', '/#tarifs')
  })

  it('reste entièrement localisée en anglais, y compris la capture', async () => {
    mockApi({})
    const { container } = renderApp(<AppRoutes />, { route: '/', locale: 'en' })

    expect(
      await screen.findByRole('heading', {
        level: 2,
        name: 'Kivou turns recently awarded public contracts into prospects you can contact at the right time.',
      }),
    ).toBeInTheDocument()
    expect(container.textContent).toContain('CONTINUOUS SALES MONITORING')
    expect(container.textContent).toContain('Target profile')
    expect(container.textContent).toContain('IN YOUR DASHBOARD')
    expect(container.textContent).toContain('Verified company details')
    expect(container.textContent).not.toContain('SURVEILLANCE COMMERCIALE CONTINUE')
    expect(container.textContent).not.toContain('Votre profil de ciblage')

    const image = screen.getByRole('img', {
      name: /Kivou dashboard showing a sales signal for a recently awarded company/i,
    })
    expect(image).toHaveAttribute('src', '/demo/kivou-dashboard-en-desktop.webp')
    expect(image.closest('picture')!.querySelector('source[media="(max-width: 767px)"]')).toHaveAttribute(
      'srcset',
      '/demo/kivou-dashboard-en-mobile.webp',
    )
  })

  it('conserve les ancres comment et tarifs pendant la transition commerciale', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    renderApp(<AppRoutes />, { route: '/' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('link', { name: 'Comparer les offres' }))

    await waitFor(() => expect(document.activeElement?.id).toBe('tarifs'))
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: 'Choisissez le rythme adapté à votre prospection',
      }),
    ).toBeInTheDocument()
  })

  it('met les quatre offres complètes et leurs prix au premier plan', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })
    renderApp(<AppRoutes />, { route: '/' })

    const title = await screen.findByRole('heading', {
      level: 2,
      name: 'Choisissez le rythme adapté à votre prospection',
    })
    const section = title.closest('section')!

    expect(within(section).getAllByRole('article')).toHaveLength(4)

    const expectedPlans = [
      ['Découverte', 'Gratuit', 'Pour découvrir la qualité des signaux avec votre propre ciblage.'],
      ['Essential', '49', 'Pour prospecter régulièrement sur un marché prioritaire.'],
      ['Pro', '99', 'Pour suivre plusieurs priorités commerciales au quotidien.'],
      ['Scale', '199', 'Pour couvrir davantage de marchés avec une cadence renforcée.'],
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
      name: 'Choisissez le rythme adapté à votre prospection',
    })

    expect(screen.getByText('Les tarifs sont momentanément indisponibles. La création de compte reste ouverte.')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/CHF\s?49|CHF\s?99|CHF\s?199/)
  })
})

describe('coordonnées professionnelles de la démonstration dashboard', () => {
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
