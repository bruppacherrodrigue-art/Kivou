import { describe, expect, it, afterEach, beforeEach, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import { AUTHENTICATED, DISCOVERY_STATUS, PRO_STATUS, mockApi, renderApp } from '../test/harness'
import { saveCheckoutIntent, readCheckoutIntent } from './checkoutIntent'

/* P0-03 §9 à §12 — le retour de paiement, et la seule chose qui l'autorise.
 *
 * Le navigateur ne prouve JAMAIS un paiement. Ni l'URL de retour, ni l'état de
 * navigation, ni le stockage, ni un paramètre de requête : tous sont
 * fabricables par quiconque ouvre l'adresse. La seule autorité est
 * `GET /billing/status`, qui ne bascule qu'une fois le webhook traité côté
 * serveur.
 *
 * D'où la formulation : cet écran n'annonce pas « votre paiement est passé »,
 * il annonce « vos droits payants sont actifs ». La différence compte pour un
 * client déjà payant qui ouvre l'URL à la main — ce que rien n'empêche.
 */

const POLL = 2500
const TIMEOUT = 45_000

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  sessionStorage.clear()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

/** Une suite de réponses `/billing/status`, consommée dans l'ordre. */
function statusSequence(steps: ({ status?: number; body?: unknown } | 'network')[]) {
  let call = 0
  return mockApi({
    'GET /billing/status': () => {
      const step = steps[Math.min(call, steps.length - 1)]
      call += 1
      if (step === 'network') return { status: 500, body: { detail: { code: 'billing_error' } } }
      return step
    },
    'GET /signals': { body: { items: [], total_returned: 0 } },
  })
}

function openSuccess() {
  renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout/success' })
}

const paid = { body: PRO_STATUS }
const free = { body: DISCOVERY_STATUS }

describe('confirmation du retour de paiement', () => {
  it('A — passe de la vérification à l’accès actif quand le serveur bascule', async () => {
    statusSequence([free, free, paid])
    openSuccess()

    expect(await screen.findByText('Vérification de votre accès')).toBeInTheDocument()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL * 2)
    })
    expect(await screen.findByText('Accès payant actif')).toBeInTheDocument()
    expect(screen.getByText(/Votre offre Pro est active/)).toBeInTheDocument()
  })

  it('B — s’arrête au bout de 45 secondes sans rien affirmer', async () => {
    statusSequence([free])
    openSuccess()
    await screen.findByText('Vérification de votre accès')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TIMEOUT + POLL)
    })

    expect(await screen.findByText(/Aucun accès payant n’a encore été confirmé/)).toBeInTheDocument()
    expect(screen.queryByText('Accès payant actif')).not.toBeInTheDocument()
  })

  it('C — le réessai relance la vérification et finit par confirmer', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let paidNow = false
    mockApi({
      'GET /billing/status': () => (paidNow ? paid : free),
      'GET /signals': { body: { items: [], total_returned: 0 } },
    })
    openSuccess()
    await screen.findByText('Vérification de votre accès')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TIMEOUT + POLL)
    })
    const retry = await screen.findByRole('button', { name: 'Réessayer la vérification' })
    expect(retry).toBeEnabled()

    paidNow = true
    await user.click(retry)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL)
    })

    expect(await screen.findByText('Accès payant actif')).toBeInTheDocument()
  })

  it('D — une lecture ratée n’annonce aucun échec et la confirmation arrive', async () => {
    statusSequence(['network', 'network', paid])
    openSuccess()
    await screen.findByText('Vérification de votre accès')

    // Aucun message d'échec pendant les tentatives ratées.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL * 2)
    })
    expect(await screen.findByText('Accès payant actif')).toBeInTheDocument()
  })

  it('E — une arrivée directe sans paiement ne confirme jamais rien', async () => {
    statusSequence([free])
    openSuccess()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TIMEOUT + POLL)
    })

    expect(screen.queryByText('Accès payant actif')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Accéder à mes signaux' })).not.toBeInTheDocument()
  })

  it('F — un compte déjà payant voit ses droits, sans qu’un paiement soit affirmé', async () => {
    statusSequence([paid])
    openSuccess()

    expect(await screen.findByText('Accès payant actif')).toBeInTheDocument()
    const page = document.body.textContent ?? ''
    // Rien ne prétend qu'un paiement vient d'avoir lieu : cette page peut être
    // ouverte à la main par un client payant depuis des semaines.
    expect(page).not.toMatch(/paiement (confirmé|reçu|effectué|transmis)/i)
    expect(page).not.toMatch(/merci pour votre paiement/i)
  })

  it('le sondage reste borné : il ne rappelle plus le serveur après le délai', async () => {
    const handler = statusSequence([free])
    openSuccess()
    await screen.findByText('Vérification de votre accès')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TIMEOUT + POLL)
    })
    const afterTimeout = handler.mock.calls.length

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL * 10)
    })
    expect(handler.mock.calls.length).toBe(afterTimeout)
  })
})

describe('retour au signal qui a déclenché l’achat', () => {
  it('propose de revenir au signal quand une intention valide existe', async () => {
    saveCheckoutIntent('sig_locked_1')
    statusSequence([paid])
    openSuccess()

    const cta = await screen.findByRole('link', { name: 'Revenir à ce signal' })
    expect(cta).toHaveAttribute('href', '/app/signals/sig_locked_1')
    expect(screen.getByRole('link', { name: 'Voir tous mes signaux' })).toBeInTheDocument()
  })

  it('propose le feed quand aucune intention n’existe', async () => {
    statusSequence([paid])
    openSuccess()

    expect(await screen.findByRole('link', { name: 'Accéder à mes signaux' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Revenir à ce signal' })).not.toBeInTheDocument()
  })

  it('efface l’intention en repartant vers le signal', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    saveCheckoutIntent('sig_locked_1')
    mockApi({
      'GET /billing/status': paid,
      'GET /signals/sig_locked_1': { status: 404, body: { detail: { code: 'signal_not_found' } } },
    })
    openSuccess()

    await user.click(await screen.findByRole('link', { name: 'Revenir à ce signal' }))
    expect(readCheckoutIntent()).toBeNull()
  })

  it('ne propose aucun retour tant que le serveur n’a pas confirmé', async () => {
    saveCheckoutIntent('sig_locked_1')
    statusSequence([free])
    openSuccess()

    await screen.findByText('Vérification de votre accès')
    expect(screen.queryByRole('link', { name: 'Revenir à ce signal' })).not.toBeInTheDocument()
  })

  it('ignore une intention corrompue plutôt que de fabriquer une route', async () => {
    sessionStorage.setItem('kivou.checkout-intent', 'a'.repeat(500))
    statusSequence([paid])
    openSuccess()

    expect(await screen.findByRole('link', { name: 'Accéder à mes signaux' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Revenir à ce signal' })).not.toBeInTheDocument()
  })
})

describe('annulation', () => {
  it('efface l’intention et n’annonce aucun échec', async () => {
    saveCheckoutIntent('sig_locked_1')
    mockApi({})
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout/cancel' })

    expect(await screen.findByText('Paiement interrompu')).toBeInTheDocument()
    await waitFor(() => expect(readCheckoutIntent()).toBeNull())

    const page = document.body.textContent ?? ''
    expect(page).not.toMatch(/échec|refus|erreur de paiement/i)
    expect(page).toMatch(/Rien n’a été débité/)
  })
})
