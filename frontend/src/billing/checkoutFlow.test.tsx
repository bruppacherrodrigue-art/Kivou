import { describe, expect, it, afterEach, beforeEach, vi } from 'vitest'
import { StrictMode } from 'react'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation, useNavigate } from 'react-router-dom'
import { AppRoutes } from '../App'
import { CheckoutHandoff } from '../reference/dashboard/CheckoutHandoff'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  PRO_STATUS,
  callsTo,
  mockApi,
  recordedCalls,
  renderApp,
} from '../test/harness'
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

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>
}

function CheckoutQueryChanger() {
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => navigate('/checkout?plan=essential')}>
        Choisir Essentiel
      </button>
      <CheckoutHandoff />
      <LocationProbe />
    </>
  )
}

const paid = { body: PRO_STATUS }
const free = { body: DISCOVERY_STATUS }

describe('passage autoritaire vers Stripe', () => {
  it('relance localement le catalogue après une erreur sans ouvrir de checkout', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let attempt = 0
    mockApi({
      'GET /billing/plans': () => {
        attempt += 1
        return attempt === 1
          ? { status: 503, body: { detail: { code: 'billing_unavailable' } } }
          : { body: CATALOGUE }
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout?plan=pro' })

    await user.click(await screen.findByRole('button', {
      name: 'Réessayer le chargement du catalogue',
    }))

    expect(await screen.findByRole('heading', { name: 'Finaliser l’offre Pro' })).toBeVisible()
    expect(callsTo('/billing/plans', 'GET')).toHaveLength(2)
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })

  it('accepte l’unique catalogue réel après un changement de plan pendant son chargement', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let release!: (value: { body: typeof CATALOGUE }) => void
    const response = new Promise<{ body: typeof CATALOGUE }>((resolve) => {
      release = resolve
    })
    mockApi({ 'GET /billing/plans': () => response })
    renderApp(<CheckoutQueryChanger />, {
      session: AUTHENTICATED,
      route: '/checkout?plan=pro',
    })

    expect(await screen.findByRole('heading', { name: 'Chargement de l’offre' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Choisir Essentiel' }))

    await act(async () => {
      release({ body: CATALOGUE })
      await response
    })

    expect(await screen.findByRole('heading', { name: 'Finaliser l’offre Essentiel' })).toBeVisible()
    expect(screen.getByTestId('location')).toHaveTextContent('/checkout?plan=essential')
    expect(callsTo('/billing/plans', 'GET')).toHaveLength(1)
  })

  it('invalide une URL checkout devenue obsolète sans réarmer le POST avant sa réponse', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    let release!: (value: {
      body: { checkout_url: string; plan: string; currency: string }
    }) => void
    const response = new Promise<{
      body: { checkout_url: string; plan: string; currency: string }
    }>((resolve) => {
      release = resolve
    })
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    mockApi({
      'GET /billing/plans': { body: CATALOGUE },
      'POST /billing/checkout': () => response,
    })
    renderApp(<CheckoutQueryChanger />, {
      session: AUTHENTICATED,
      route: '/checkout?plan=pro',
    })

    await user.click(await screen.findByRole('button', { name: 'Continuer vers Stripe' }))
    await waitFor(() => expect(callsTo('/billing/checkout')).toHaveLength(1))
    await user.click(screen.getByRole('button', { name: 'Choisir Essentiel' }))

    expect(await screen.findByRole('heading', { name: 'Finaliser l’offre Essentiel' })).toBeVisible()
    const currentSubmit = screen.getByRole('button', { name: 'Continuer vers Stripe' })
    expect(currentSubmit).toBeDisabled()
    fireEvent.click(currentSubmit)
    expect(callsTo('/billing/checkout')).toHaveLength(1)

    await act(async () => {
      release({
        body: {
          checkout_url: 'https://checkout.stripe.test/cs_stale_pro',
          plan: 'pro',
          currency: 'chf',
        },
      })
      await response
    })

    expect(assign).toHaveBeenCalledTimes(0)
    expect(screen.getByRole('button', { name: 'Continuer vers Stripe' })).toBeEnabled()
  })

  it('charge le catalogue avant de créer un Checkout pour un plan achetable', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    const reversedCurrencies = { ...CATALOGUE, currencies: ['eur', 'chf'] as const }
    mockApi({
      'GET /billing/plans': { body: reversedCurrencies },
      'POST /billing/checkout': {
        body: {
          checkout_url: 'https://checkout.stripe.test/cs_reference',
          plan: 'pro',
          currency: 'chf',
        },
      },
    })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout?plan=pro' })

    expect(await screen.findByRole('heading', { name: 'Finaliser l’offre Pro' })).toBeVisible()
    const catalogueNote = screen.getByRole('note')
    expect(catalogueNote).toHaveClass('prototype-notice')
    expect(catalogueNote).toHaveTextContent(/prix et les droits.*catalogue Kivou/i)
    expect(callsTo('/billing/checkout')).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: 'Continuer vers Stripe' }))

    await waitFor(() => expect(callsTo('/billing/checkout')).toHaveLength(1))
    expect(callsTo('/billing/checkout')[0].body).toEqual({ plan: 'pro', currency: 'chf' })
    expect(recordedCalls.map((call) => `${call.method} ${call.url}`)).toEqual([
      'GET /billing/plans',
      'POST /billing/checkout',
    ])
    expect(assign).toHaveBeenCalledWith('https://checkout.stripe.test/cs_reference')
  })

  it.each([
    'http://checkout.stripe.test/cs_insecure',
    'https://user:password@checkout.stripe.test/cs_credentials',
    'destination-invalide',
  ])('refuse localement la destination checkout invalide %s', async (checkoutUrl) => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    mockApi({
      'GET /billing/plans': { body: CATALOGUE },
      'POST /billing/checkout': {
        body: {
          checkout_url: checkoutUrl,
          plan: 'pro',
          currency: 'chf',
        },
      },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout?plan=pro' })

    await user.click(await screen.findByRole('button', { name: 'Continuer vers Stripe' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'La destination de paiement reçue est invalide',
    )
    expect(assign).not.toHaveBeenCalled()
  })

  it('verrouille deux demandes checkout dans le même tour de boucle', async () => {
    let release!: (value: { body: { checkout_url: string; plan: string; currency: string } }) => void
    const response = new Promise<{
      body: { checkout_url: string; plan: string; currency: string }
    }>((resolve) => {
      release = resolve
    })
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    mockApi({
      'GET /billing/plans': { body: CATALOGUE },
      'POST /billing/checkout': () => response,
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout?plan=pro' })

    const submit = await screen.findByRole('button', { name: 'Continuer vers Stripe' })
    act(() => {
      fireEvent.click(submit)
      fireEvent.click(submit)
    })
    expect(callsTo('/billing/checkout')).toHaveLength(1)

    await act(async () => {
      release({
        body: {
          checkout_url: 'https://checkout.stripe.test/cs_once',
          plan: 'pro',
          currency: 'chf',
        },
      })
      await response
    })
    expect(assign).toHaveBeenCalledTimes(1)
  })

  it('n’assigne aucune URL quand la réponse checkout arrive après démontage', async () => {
    let release!: (value: { body: { checkout_url: string; plan: string; currency: string } }) => void
    const response = new Promise<{
      body: { checkout_url: string; plan: string; currency: string }
    }>((resolve) => {
      release = resolve
    })
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    mockApi({
      'GET /billing/plans': { body: CATALOGUE },
      'POST /billing/checkout': () => response,
    })
    const view = renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: '/checkout?plan=pro',
    })

    fireEvent.click(await screen.findByRole('button', { name: 'Continuer vers Stripe' }))
    await waitFor(() => expect(callsTo('/billing/checkout')).toHaveLength(1))
    view.unmount()
    await act(async () => {
      release({
        body: {
          checkout_url: 'https://checkout.stripe.test/cs_late',
          plan: 'pro',
          currency: 'chf',
        },
      })
      await response
    })

    expect(assign).toHaveBeenCalledTimes(0)
  })

  it('rend Changer d’offre inerte pendant la création de la session Stripe', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const response = new Promise<never>(() => {})
    mockApi({
      'GET /billing/plans': { body: CATALOGUE },
      'POST /billing/checkout': () => response,
    })
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      { session: AUTHENTICATED, route: '/checkout?plan=pro' },
    )

    await user.click(await screen.findByRole('button', { name: 'Continuer vers Stripe' }))
    const changer = screen.getByRole('link', { name: 'Changer d’offre' })
    expect(changer).toHaveAttribute('aria-disabled', 'true')
    await user.click(changer)
    expect(screen.getByTestId('location')).toHaveTextContent('/checkout?plan=pro')
  })

  it('replie un plan inconnu sur Découverte sans paiement ni stockage', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    mockApi({ 'GET /billing/plans': { body: CATALOGUE } })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout?plan=founding' })

    expect(await screen.findByRole('heading', { name: 'Aucun paiement nécessaire' })).toBeVisible()
    const discoveryNote = screen.getByRole('note')
    expect(discoveryNote).toHaveClass('prototype-notice')
    expect(discoveryNote).toHaveTextContent('Aucune session Stripe n’est créée')
    expect(screen.getByRole('link', { name: 'Voir 3 signaux' })).toHaveAttribute(
      'href',
      '/app/signals',
    )
    expect(callsTo('/billing/checkout')).toHaveLength(0)
    expect(storage).not.toHaveBeenCalled()
  })

  it.each([
    [0, 'Voir 0 signaux', '0 signaux accordés'],
    [1, 'Voir 1 signal', '1 signal accordé'],
  ] as const)('rend le nombre Discovery autoritaire pour %i signal', async (count, cta, summary) => {
    const catalogue = {
      ...CATALOGUE,
      plans: CATALOGUE.plans.map((plan) =>
        plan.plan_code === 'discovery'
          ? { ...plan, entitlements: { ...plan.entitlements, granted_signals: count } }
          : plan,
      ),
    }
    mockApi({ 'GET /billing/plans': { body: catalogue } })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout?plan=discovery' })

    expect(await screen.findByRole('link', { name: cta })).toHaveAttribute('href', '/app/signals')
    expect(screen.getByText(new RegExp(summary))).toBeVisible()
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })

  it('pluralise le nombre de profils Discovery fourni par le catalogue', async () => {
    const catalogue = {
      ...CATALOGUE,
      plans: CATALOGUE.plans.map((plan) =>
        plan.plan_code === 'discovery'
          ? { ...plan, entitlements: { ...plan.entitlements, max_active_icps: 2 } }
          : plan,
      ),
    }
    mockApi({ 'GET /billing/plans': { body: catalogue } })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout?plan=discovery' })

    expect(await screen.findByText(/2 profils ·/)).toBeVisible()
  })

  it('refuse localement un plan non achetable ou sans prix dans la devise', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const unavailable = {
      ...CATALOGUE,
      plans: CATALOGUE.plans.map((plan) =>
        plan.plan_code === 'pro'
          ? { ...plan, purchasable: false, monthly_price: {} }
          : plan,
      ),
    }
    mockApi({ 'GET /billing/plans': { body: unavailable } })

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout?plan=pro' })

    expect(await screen.findByRole('alert')).toHaveTextContent(/indisponible/i)
    expect(screen.queryByRole('button', { name: 'Continuer vers Stripe' })).not.toBeInTheDocument()
    expect(callsTo('/billing/checkout')).toHaveLength(0)
    await user.tab()
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })
})

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

  it('borne aussi une requête billing.status qui ne se résout jamais', async () => {
    mockApi({
      'GET /billing/status': () => new Promise<never>(() => {}),
    })
    openSuccess()
    await screen.findByText('Vérification de votre accès')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TIMEOUT)
    })

    expect(await screen.findByText(/Aucun accès payant n’a encore été confirmé/)).toBeVisible()
  })

  it('ne laisse aucune continuation ni aucun timer quand une requête se résout après démontage', async () => {
    let release!: (value: typeof free) => void
    const response = new Promise<typeof free>((resolve) => {
      release = resolve
    })
    const handler = mockApi({ 'GET /billing/status': () => response })
    const view = renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: '/checkout/success',
    })
    await screen.findByText('Vérification de votre accès')
    expect(handler).toHaveBeenCalledTimes(1)

    view.unmount()
    await act(async () => {
      release(free)
      await response
    })
    expect(vi.getTimerCount()).toBe(0)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL * 3)
    })
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('ne crée qu’une chaîne de polling courante sous StrictMode', async () => {
    const handler = statusSequence([free])
    const view = renderApp(
      <StrictMode>
        <AppRoutes />
      </StrictMode>,
      { session: AUTHENTICATED, route: '/checkout/success' },
    )
    await screen.findByText('Vérification de votre accès')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(handler).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL)
    })
    expect(handler).toHaveBeenCalledTimes(2)
    view.unmount()
    expect(vi.getTimerCount()).toBe(0)
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

  it('deux clics de rafraîchissement dans le même tour ne lancent qu’une nouvelle chaîne', async () => {
    let calls = 0
    let hold = false
    mockApi({
      'GET /billing/status': () => {
        calls += 1
        return hold ? new Promise<never>(() => {}) : free
      },
    })
    openSuccess()
    await screen.findByText('Vérification de votre accès')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TIMEOUT + POLL)
    })
    const retry = await screen.findByRole('button', { name: 'Réessayer la vérification' })
    const beforeRefresh = calls
    hold = true

    act(() => {
      fireEvent.click(retry)
      fireEvent.click(retry)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(calls).toBe(beforeRefresh + 1)
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
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
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

    expect(await screen.findByText('Retour depuis le parcours de paiement')).toBeInTheDocument()
    await waitFor(() => expect(readCheckoutIntent()).toBeNull())

    const page = document.body.textContent ?? ''
    expect(page).not.toMatch(/échec|refus|erreur de paiement/i)
    expect(page).toMatch(/Cette page ne modifie pas votre accès/)
  })
})
