import { describe, expect, it, afterEach, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router-dom'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_DETAIL,
  LOCKED_ITEM,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

/* P0-03 §6, §16 — l'intention commerciale traverse le paywall, et RIEN d'autre.
 *
 * Un client qui clique depuis un signal verrouillé veut revenir à CE signal
 * après avoir payé. Seule sa clé voyage. Tout le reste — entreprise gagnante,
 * montant, besoins, preuve, source, profil visé — est précisément ce que le
 * paywall protège : le faire transiter par l'état de navigation, une URL ou le
 * stockage le livrerait à un compte qui n'y a pas encore droit, sans que le
 * serveur ait rien décidé.
 */

afterEach(() => {
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

/** Rend l'état de navigation courant, pour lire ce qui a réellement voyagé. */
function NavigationStateProbe() {
  const location = useLocation()
  return <p data-testid="nav-state">{JSON.stringify(location.state ?? null)}</p>
}

const BILLING_ROUTES = {
  'GET /billing/plans': { body: CATALOGUE },
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /target-icps': { body: [ICP] },
}

/** Ce qu'un état de navigation ne doit JAMAIS contenir. */
const PROTECTED = [
  'Constructions Bertrand',
  '12345678900011',
  'Réfection de la voirie',
  'boamp.fr',
  '26-104412',
  '1240000',
  'icp_1',
  'Travaux publics',
  'Matériaux ou composants',
]

describe('depuis le feed verrouillé', () => {
  it('transmet la clé du signal, et seulement elle', async () => {
    const user = userEvent.setup()
    mockApi({ ...BILLING_ROUTES, 'GET /signals': { body: feedPage([LOCKED_ITEM]) } })
    renderApp(
      <>
        <AppRoutes />
        <NavigationStateProbe />
      </>,
      { session: AUTHENTICATED, route: '/app/signals' },
    )

    await user.click(await screen.findByRole('link', { name: /Déverrouiller Kivou/ }))
    await screen.findByRole('button', { name: /Choisir Pro/ })

    const state = JSON.parse(screen.getByTestId('nav-state').textContent ?? 'null')
    expect(state).toEqual({ lockedSignalKey: 'sig_locked_1' })
  })

  it('ne laisse fuir aucune donnée protégée dans l’état de navigation', async () => {
    const user = userEvent.setup()
    mockApi({ ...BILLING_ROUTES, 'GET /signals': { body: feedPage([LOCKED_ITEM]) } })
    renderApp(
      <>
        <AppRoutes />
        <NavigationStateProbe />
      </>,
      { session: AUTHENTICATED, route: '/app/signals' },
    )

    await user.click(await screen.findByRole('link', { name: /Déverrouiller Kivou/ }))
    await screen.findByRole('button', { name: /Choisir Pro/ })

    const serialised = screen.getByTestId('nav-state').textContent ?? ''
    for (const secret of PROTECTED) {
      expect(serialised).not.toContain(secret)
    }
  })
})

describe('depuis le détail verrouillé', () => {
  it('transmet la clé du signal, et seulement elle', async () => {
    const user = userEvent.setup()
    mockApi({
      ...BILLING_ROUTES,
      'GET /signals/sig_locked_1': { body: LOCKED_DETAIL },
    })
    renderApp(
      <>
        <AppRoutes />
        <NavigationStateProbe />
      </>,
      { session: AUTHENTICATED, route: '/app/signals/sig_locked_1' },
    )

    await user.click(await screen.findByRole('link', { name: 'Voir les offres' }))
    await screen.findByRole('button', { name: /Choisir Pro/ })

    const state = JSON.parse(screen.getByTestId('nav-state').textContent ?? 'null')
    expect(state).toEqual({ lockedSignalKey: 'sig_locked_1' })
  })

  it('ne laisse fuir aucune donnée protégée depuis le détail', async () => {
    const user = userEvent.setup()
    mockApi({ ...BILLING_ROUTES, 'GET /signals/sig_locked_1': { body: LOCKED_DETAIL } })
    renderApp(
      <>
        <AppRoutes />
        <NavigationStateProbe />
      </>,
      { session: AUTHENTICATED, route: '/app/signals/sig_locked_1' },
    )

    await user.click(await screen.findByRole('link', { name: 'Voir les offres' }))
    await screen.findByRole('button', { name: /Choisir Pro/ })

    const serialised = screen.getByTestId('nav-state').textContent ?? ''
    for (const secret of PROTECTED) {
      expect(serialised).not.toContain(secret)
    }
  })
})

describe('avant tout paiement réel', () => {
  it('n’écrit rien dans le stockage tant qu’aucun Checkout n’a abouti', async () => {
    const user = userEvent.setup()
    mockApi({ ...BILLING_ROUTES, 'GET /signals': { body: feedPage([LOCKED_ITEM]) } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await user.click(await screen.findByRole('link', { name: /Déverrouiller Kivou/ }))
    await screen.findByRole('button', { name: /Choisir Pro/ })

    // Arriver sur la facturation n'est pas acheter : rien n'est mémorisé.
    expect(sessionStorage.length).toBe(0)
  })

  it('ne mémorise rien quand l’ouverture du paiement échoue', async () => {
    const user = userEvent.setup()
    mockApi({
      ...BILLING_ROUTES,
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
      'POST /billing/checkout': {
        status: 409,
        body: { detail: { code: 'checkout_in_progress' } },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await user.click(await screen.findByRole('link', { name: /Déverrouiller Kivou/ }))
    await user.click(await screen.findByRole('button', { name: /Choisir Pro/ }))
    await screen.findByRole('alert')

    // Une intention orpheline survivrait à un parcours qui n'a jamais eu lieu.
    expect(sessionStorage.length).toBe(0)
  })

  it('mémorise la clé une fois le paiement réellement ouvert', async () => {
    const user = userEvent.setup()
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    mockApi({
      ...BILLING_ROUTES,
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
      'POST /billing/checkout': {
        body: {
          checkout_url: 'https://checkout.stripe.test/cs_1',
          plan: 'pro',
          currency: 'chf',
        },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await user.click(await screen.findByRole('link', { name: /Déverrouiller Kivou/ }))
    await user.click(await screen.findByRole('button', { name: /Choisir Pro/ }))

    expect(assign).toHaveBeenCalledWith('https://checkout.stripe.test/cs_1')
    expect(JSON.stringify(sessionStorage)).toContain('sig_locked_1')
    // Et toujours rien du signal lui-même.
    for (const secret of PROTECTED) {
      expect(JSON.stringify(sessionStorage)).not.toContain(secret)
    }
  })

  it('n’écrit aucune intention quand on arrive à la facturation sans signal', async () => {
    const user = userEvent.setup()
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    mockApi({
      ...BILLING_ROUTES,
      'POST /billing/checkout': {
        body: {
          checkout_url: 'https://checkout.stripe.test/cs_1',
          plan: 'pro',
          currency: 'chf',
        },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })

    await user.click(await screen.findByRole('button', { name: /Choisir Pro/ }))
    expect(assign).toHaveBeenCalled()
    expect(sessionStorage.length).toBe(0)
  })
})
