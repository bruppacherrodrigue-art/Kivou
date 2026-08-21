import { describe, expect, it, afterEach, beforeEach, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  PRO_STATUS,
  UNAUTHENTICATED,
  callsTo,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

/* SPEC-015 §53 — les onze vérifications de facturation. */

const assign = vi.fn()

beforeEach(() => {
  assign.mockClear()
  // `window.location.assign` est la frontière de sortie : on l'observe, on ne
  // la suit pas — un vrai chargement de page tuerait le test.
  vi.stubGlobal('location', { ...window.location, assign })
})

afterEach(() => vi.unstubAllGlobals())

const BASE = {
  'GET /billing/plans': { body: CATALOGUE },
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /target-icps': { body: [ICP] },
  'GET /signals': { body: feedPage([]) },
}

describe('grille tarifaire', () => {
  it('affiche les prix RENVOYÉS par l’API, jamais une grille écrite en dur', async () => {
    mockApi(BASE)
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })

    await screen.findByText('Essential')

    // Chaque montant est vérifié DANS sa carte : « 99 » est un sous-texte de
    // « 199 », et une recherche globale confondrait Pro et Scale.
    const priceOf = (plan: string) => {
      const heading = screen.getByRole('heading', { name: plan })
      return heading.closest('article')!.textContent ?? ''
    }

    // Les montants viennent du catalogue : 0 / 49 / 99 / 199, en CHF par défaut.
    expect(priceOf('Découverte')).toContain('Gratuit')
    expect(priceOf('Essential')).toMatch(/49/)
    expect(priceOf('Pro')).toMatch(/(^|\D)99/)
    expect(priceOf('Scale')).toMatch(/199/)

    // Les anciens prix des maquettes ne doivent apparaître nulle part.
    const page = document.body.textContent ?? ''
    for (const obsolete of ['29', '59', '129']) {
      expect(page).not.toMatch(new RegExp(`${obsolete}[.,]00`))
    }
  })

  it('désigne Pro comme l’offre recommandée', async () => {
    mockApi(BASE)
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })

    const recommended = await screen.findByText('Recommandé')
    const card = recommended.closest('article')!
    expect(within(card).getByRole('heading', { name: 'Pro' })).toBeInTheDocument()
    // Une seule offre porte la marque : sinon aucune n'est mise en avant.
    expect(screen.getAllByText('Recommandé')).toHaveLength(1)
  })

  it('n’affiche jamais l’offre Founding sur une grille publique', async () => {
    mockApi({ ...BASE, 'GET /me': { status: 401, body: {} } })
    renderApp(<AppRoutes />, { session: UNAUTHENTICATED, route: '/' })

    await screen.findByText('Essential')
    const page = (document.body.textContent ?? '').toLowerCase()
    expect(page).not.toContain('founding')
    expect(page).not.toContain('fondateur')
    expect(page).not.toContain('design partner')
    expect(page).not.toMatch(/\b29\b/)
  })
})

describe('devise', () => {
  it('demande un choix EXPLICITE, jamais déduit de la langue', async () => {
    const user = userEvent.setup()
    mockApi(BASE)
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing', locale: 'fr' })

    const group = await screen.findByRole('group', { name: 'Devise' })
    expect(within(group).getByLabelText('CHF')).toBeInTheDocument()
    expect(within(group).getByLabelText('EUR')).toBeInTheDocument()

    // Une locale française ne présélectionne PAS l'euro.
    expect(within(group).getByLabelText('CHF')).toBeChecked()
    await user.click(within(group).getByLabelText('EUR'))
    expect(within(group).getByLabelText('EUR')).toBeChecked()
  })
})

describe('checkout', () => {
  it('n’envoie que le plan et la devise — aucun identifiant de prix', async () => {
    const user = userEvent.setup()
    mockApi({
      ...BASE,
      'POST /billing/checkout': {
        body: {
          checkout_url: 'https://checkout.stripe.com/c/pay/cs_test_123',
          plan: 'pro',
          currency: 'chf',
        },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })

    await user.click(await screen.findByRole('button', { name: 'Choisir Pro' }))

    await waitFor(() => expect(callsTo('/billing/checkout')).toHaveLength(1))
    const sent = callsTo('/billing/checkout')[0].body as Record<string, unknown>
    expect(sent).toEqual({ plan: 'pro', currency: 'chf' })

    const serialised = JSON.stringify(sent)
    expect(serialised).not.toContain('price_')
    expect(serialised).not.toContain('coupon')
    expect(serialised).not.toContain('lookup_key')
    expect(serialised).not.toContain('founding')
    expect(serialised).not.toContain('account_id')
  })

  it('redirige vers l’URL Stripe renvoyée par le backend', async () => {
    const user = userEvent.setup()
    mockApi({
      ...BASE,
      'POST /billing/checkout': {
        body: {
          checkout_url: 'https://checkout.stripe.com/c/pay/cs_test_456',
          plan: 'essential',
          currency: 'chf',
        },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })

    await user.click(await screen.findByRole('button', { name: 'Choisir Essential' }))

    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith('https://checkout.stripe.com/c/pay/cs_test_456'),
    )
  })

  it('rend « paiement déjà ouvert » comme un état, sans boucler', async () => {
    const user = userEvent.setup()
    mockApi({
      ...BASE,
      'POST /billing/checkout': {
        status: 409,
        body: {
          detail: {
            code: 'checkout_in_progress',
            message: 'un paiement est déjà en cours',
            expires_at: '2026-08-18T12:30:00+00:00',
          },
        },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })

    await user.click(await screen.findByRole('button', { name: 'Choisir Pro' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Un paiement est déjà ouvert')
    expect(alert).toHaveTextContent('Terminez-la, ou réessayez après son expiration.')
    // La date d'expiration renvoyée par le backend est rendue lisible.
    expect(alert.textContent).toMatch(/expire le/)

    // Un seul appel : aucune relance automatique.
    expect(callsTo('/billing/checkout')).toHaveLength(1)
    expect(assign).not.toHaveBeenCalled()
  })
})

describe('compte payant', () => {
  it('propose la gestion de facturation plutôt qu’un second paiement', async () => {
    mockApi({ ...BASE, 'GET /billing/status': { body: PRO_STATUS } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })

    expect(await screen.findByRole('button', { name: 'Gérer ma facturation' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Choisir/ })).not.toBeInTheDocument()
    expect(screen.getByText(/Prochain renouvellement le/)).toBeInTheDocument()
  })

  it('ouvre le portail du prestataire sans en reconstruire les écrans', async () => {
    const user = userEvent.setup()
    mockApi({
      ...BASE,
      'GET /billing/status': { body: PRO_STATUS },
      'POST /billing/portal': { body: { portal_url: 'https://billing.stripe.com/p/session/xyz' } },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })

    await user.click(await screen.findByRole('button', { name: 'Gérer ma facturation' }))
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith('https://billing.stripe.com/p/session/xyz'),
    )

    // Aucun écran de moyen de paiement, de facture ou de résiliation n'est
    // reconstruit dans Kivou.
    const page = (document.body.textContent ?? '').toLowerCase()
    expect(page).not.toContain('numéro de carte')
    expect(page).not.toContain('cvc')
    expect(page).not.toContain('turiya')
  })

  it('gère l’absence de dossier de facturation sans trace technique', async () => {
    const user = userEvent.setup()
    mockApi({
      ...BASE,
      'GET /billing/status': { body: PRO_STATUS },
      'POST /billing/portal': {
        status: 409,
        body: { detail: { code: 'no_billing_customer', message: 'aucun dossier' } },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })

    await user.click(await screen.findByRole('button', { name: 'Gérer ma facturation' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Aucun dossier de facturation')
    expect(assign).not.toHaveBeenCalled()
  })
})

describe('retour de paiement', () => {
  it('n’accorde AUCUN accès depuis la page de succès : elle relit l’état serveur', async () => {
    mockApi({ ...BASE, 'GET /billing/status': { body: DISCOVERY_STATUS } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout/success' })

    // Tant que le backend dit « discovery », la page reste en attente.
    expect(await screen.findByRole('heading', { name: 'Vérification de votre accès' }))
      .toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Accès payant actif' }),
    ).not.toBeInTheDocument()
    // Aucun accès n'est proposé avant confirmation.
    expect(screen.queryByRole('link', { name: 'Accéder à mes signaux' })).not.toBeInTheDocument()

    // L'état a bien été REDEMANDÉ au serveur.
    await waitFor(() => expect(callsTo('/billing/status', 'GET').length).toBeGreaterThan(0))
    // Et rien n'a été écrit depuis le navigateur.
    expect(callsTo('/billing/status', 'PATCH')).toHaveLength(0)
    expect(callsTo('/billing/status', 'POST')).toHaveLength(0)
  })

  it('confirme l’accès seulement quand l’état serveur a basculé', async () => {
    mockApi({ ...BASE, 'GET /billing/status': { body: PRO_STATUS } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout/success' })

    expect(
      await screen.findByRole('heading', { name: 'Accès payant actif' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Accéder à mes signaux' })).toHaveAttribute(
      'href',
      '/app/signals',
    )
  })

  it('n’annonce aucun échec quand le client a simplement quitté le paiement', async () => {
    mockApi(BASE)
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout/cancel' })

    expect(await screen.findByRole('heading', { name: 'Paiement interrompu' })).toBeInTheDocument()
    expect(screen.getByText(/Rien n’a été débité/)).toBeInTheDocument()

    const page = (document.body.textContent ?? '').toLowerCase()
    expect(page).not.toContain('échec')
    expect(page).not.toContain('refusé')
    expect(page).not.toContain('erreur')

    // Aucune mutation de facturation.
    expect(callsTo('/billing/checkout')).toHaveLength(0)
    expect(callsTo('/billing/portal')).toHaveLength(0)
  })
})
