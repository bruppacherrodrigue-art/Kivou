import { describe, expect, it, afterEach, beforeEach, vi } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_DETAIL,
  ME,
  PRO_STATUS,
  RECOVER_STATUS,
  feedPage,
  LOCKED_ITEM,
  mockApi,
  renderApp,
} from '../test/harness'
import { readCheckoutIntent, saveCheckoutIntent } from './checkoutIntent'
import type { BillingStatus } from '../api/types'

/* Revue de supervision pré-staging — les cinq corrections.
 *
 * Chacune ferme un endroit où l'écran affirmait plus que ce que le serveur
 * garantit : un statut technique montré tel quel, un renouvellement prédit
 * pour un abonnement mort, une promesse d'accès total que les fenêtres
 * d'historique démentent, une annonce d'accessibilité perdue au moment précis
 * où elle compte, et une intention d'achat périmée qui ressurgit.
 */

afterEach(() => {
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

function billingRoutes(status: BillingStatus) {
  return {
    'GET /billing/plans': { body: CATALOGUE },
    'GET /billing/status': { body: status },
    'POST /billing/portal': { body: { portal_url: 'https://billing.stripe.test/cus_1' } },
    'POST /billing/checkout': {
      body: { checkout_url: 'https://checkout.stripe.test/cs_1', plan: 'pro', currency: 'chf' },
    },
  }
}

function renderBilling(status: BillingStatus) {
  mockApi(billingRoutes(status))
  renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/billing' })
}

// ─── 1. statut Stripe inconnu ────────────────────────────────────────────────

describe('statut Stripe inconnu', () => {
  const UNKNOWN: BillingStatus = {
    ...DISCOVERY_STATUS,
    currency: 'chf',
    subscription_status: 'something_stripe_invented_later',
    billing_action: 'contact_support',
  }

  it('ne rend jamais la chaîne technique', async () => {
    renderBilling(UNKNOWN)
    await screen.findByText('Vérification de facturation nécessaire')
    expect(document.body.textContent).not.toContain('something_stripe_invented_later')
  })

  it('affiche un état neutre à la place', async () => {
    renderBilling(UNKNOWN)
    await screen.findByText('Vérification de facturation nécessaire')
    expect(screen.getByText('À vérifier')).toBeInTheDocument()
  })

  it('n’ouvre aucun paiement', async () => {
    renderBilling(UNKNOWN)
    await screen.findByText('Vérification de facturation nécessaire')
    expect(screen.queryByRole('button', { name: /Choisir/ })).not.toBeInTheDocument()
  })

  it('laisse les statuts connus à leurs traductions', async () => {
    renderBilling(RECOVER_STATUS)
    await screen.findByText('Accès suspendu — incident de paiement')
    expect(screen.getByText('Paiement en retard')).toBeInTheDocument()
    expect(screen.queryByText('À vérifier')).not.toBeInTheDocument()
  })
})

// ─── 2. pas de renouvellement prédit hors gestion ────────────────────────────

describe('date de période', () => {
  /* Un abonnement résilié garde une `current_period_end` : c'est la fin de la
   * période déjà payée, pas une promesse de renouvellement. L'annoncer comme
   * tel, sur un écran qui propose justement de choisir une offre, dirait au
   * client qu'il est encore abonné. */
  it('n’annonce aucun renouvellement sur un abonnement terminal', async () => {
    renderBilling({
      ...DISCOVERY_STATUS,
      currency: 'chf',
      subscription_status: 'canceled',
      billing_action: 'choose_plan',
      current_period_end: '2026-09-18T00:00:00+00:00',
    })
    await screen.findByRole('button', { name: /Choisir Pro/ })
    const page = document.body.textContent ?? ''
    expect(page).not.toMatch(/Prochain renouvellement/)
    expect(page).not.toMatch(/Accès jusqu’au/)
  })

  it('n’annonce aucun renouvellement pendant un incident de paiement', async () => {
    renderBilling({ ...RECOVER_STATUS, current_period_end: '2026-09-18T00:00:00+00:00' })
    await screen.findByText('Accès suspendu — incident de paiement')
    expect(document.body.textContent).not.toMatch(/Prochain renouvellement/)
  })

  it('n’annonce aucun renouvellement quand une vérification est requise', async () => {
    renderBilling({
      ...DISCOVERY_STATUS,
      currency: 'chf',
      subscription_status: 'paused',
      billing_action: 'contact_support',
      current_period_end: '2026-09-18T00:00:00+00:00',
    })
    await screen.findByText('Vérification de facturation nécessaire')
    expect(document.body.textContent).not.toMatch(/Prochain renouvellement/)
  })

  /* Même logique pour la résiliation programmée : c'est une prédiction sur la
   * suite de l'accès. L'afficher à un compte dont l'accès est SUSPENDU dit
   * deux choses contradictoires sur le même écran. */
  it('n’annonce aucune résiliation programmée pendant un incident de paiement', async () => {
    renderBilling({
      ...RECOVER_STATUS,
      cancel_at_period_end: true,
      current_period_end: '2026-09-18T00:00:00+00:00',
    })
    await screen.findByText('Accès suspendu — incident de paiement')
    expect(document.body.textContent).not.toMatch(/Résiliation programmée/)
  })

  it('n’annonce aucune résiliation programmée quand on peut choisir une offre', async () => {
    renderBilling({
      ...DISCOVERY_STATUS,
      currency: 'chf',
      subscription_status: 'canceled',
      billing_action: 'choose_plan',
      cancel_at_period_end: true,
      current_period_end: '2026-09-18T00:00:00+00:00',
    })
    await screen.findByRole('button', { name: /Choisir Pro/ })
    expect(document.body.textContent).not.toMatch(/Résiliation programmée/)
  })

  it('garde la date sur un abonnement réellement géré', async () => {
    renderBilling(PRO_STATUS)
    await screen.findByRole('button', { name: /Gérer ma facturation/ })
    expect(document.body.textContent).toMatch(/Prochain renouvellement/)
  })
})

// ─── 3. vérité du paywall ────────────────────────────────────────────────────

describe('promesse du paywall', () => {
  /* Essential ouvre 30 jours, Pro 365, Scale tout l'historique. Un signal
   * ancien peut donc rester verrouillé après l'achat d'un plan payant. Promettre
   * « l'ensemble de votre flux » vend un accès que les droits ne donnent pas. */
  it('ne promet pas l’ensemble du flux — FR', async () => {
    mockApi({
      ...billingRoutes(DISCOVERY_STATUS),
      'GET /signals/sig_locked_1': { body: LOCKED_DETAIL },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals/sig_locked_1' })

    await screen.findByText('Ce signal est verrouillé')
    const page = document.body.textContent ?? ''
    expect(page).not.toContain('ensemble de votre flux')
    expect(page).not.toContain('flux complet')
    expect(page).toMatch(/fenêtre d’historique/)
  })

  it('ne promet pas l’ensemble du flux — EN', async () => {
    mockApi({
      ...billingRoutes(DISCOVERY_STATUS),
      'GET /signals/sig_locked_1': { body: LOCKED_DETAIL },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, {
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      route: '/app/signals/sig_locked_1',
      locale: 'en',
    })

    await screen.findByText('This signal is locked')
    const page = document.body.textContent ?? ''
    expect(page).not.toContain('whole stream')
    expect(page).not.toContain('full stream')
    expect(page).toMatch(/history window/)
  })

  it('le teaser du feed ne promet rien de plus', async () => {
    mockApi({
      ...billingRoutes(DISCOVERY_STATUS),
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    await screen.findByText('Verrouillé')
    const page = document.body.textContent ?? ''
    expect(page).not.toContain('ensemble de votre flux')
    expect(page).not.toContain('flux complet')
  })
})

// ─── 4. l'annonce d'accessibilité survit à la transition ─────────────────────

describe('région live du retour de paiement', () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
  afterEach(() => vi.useRealTimers())

  it('reste le MÊME nœud de pending à confirmé, et annonce l’accès actif', async () => {
    let paid = false
    mockApi({
      'GET /billing/status': () => ({ body: paid ? PRO_STATUS : DISCOVERY_STATUS }),
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout/success' })

    const pending = await screen.findByRole('status')
    expect(pending).toHaveAttribute('aria-live', 'polite')
    expect(pending.textContent).toMatch(/confirmation serveur/)

    paid = true
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500)
    })

    const confirmed = await screen.findByRole('status')
    // Le nœud doit SURVIVRE : démonté puis remonté, aucun lecteur d'écran
    // n'annonce le changement — et c'est précisément l'instant qui compte.
    expect(confirmed).toBe(pending)
    expect(confirmed.textContent).toMatch(/Votre offre Pro est active/)
  })
})

// ─── 5. cycle de vie de l'intention ──────────────────────────────────────────

describe('intention d’achat périmée', () => {
  it('A — un paiement générique remplace une ancienne intention par aucune', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('location', { ...window.location, assign: vi.fn() })
    saveCheckoutIntent('sig_ancien_abandonne')

    renderBilling(DISCOVERY_STATUS)
    await user.click(await screen.findByRole('button', { name: /Choisir Pro/ }))

    // Aucun signal n'a conduit ici : l'intention précédente n'a plus d'objet.
    expect(readCheckoutIntent()).toBeNull()
  })

  it('A bis — un paiement lancé depuis un signal remplace l’ancienne clé', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('location', { ...window.location, assign: vi.fn() })
    saveCheckoutIntent('sig_ancien_abandonne')

    mockApi({
      ...billingRoutes(DISCOVERY_STATUS),
      'GET /signals': { body: feedPage([LOCKED_ITEM]) },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })

    const workspace = await screen.findByTestId('signal-workspace')
    await user.click(
      await within(workspace).findByRole('button', { name: /signal verrouillé/i }),
    )
    const panel = await within(workspace).findByRole('region', {
      name: 'Détail du signal sélectionné',
    })
    await user.click(within(panel).getByRole('link', { name: 'Gérer mon accès' }))
    await user.click(await screen.findByRole('button', { name: /Choisir Pro/ }))

    expect(readCheckoutIntent()).toBe('sig_locked_1')
  })

  it('B — la confirmation vide le stockage tout en gardant le retour affiché', async () => {
    saveCheckoutIntent('sig_locked_1')
    mockApi({ 'GET /billing/status': { body: PRO_STATUS } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout/success' })

    expect(await screen.findByRole('link', { name: 'Revenir à ce signal' })).toHaveAttribute(
      'href',
      '/app/signals/sig_locked_1',
    )
    // Consommée dès la confirmation : le choix du client ne conditionne plus
    // la propreté du stockage.
    expect(readCheckoutIntent()).toBeNull()
  })

  it('C — partir vers le feed ne laisse aucune intention derrière', async () => {
    const user = userEvent.setup()
    saveCheckoutIntent('sig_locked_1')
    mockApi({
      'GET /billing/status': { body: PRO_STATUS },
      'GET /signals': { body: feedPage([]) },
      'GET /target-icps': { body: [ICP] },
    })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout/success' })

    await user.click(await screen.findByRole('link', { name: 'Voir tous mes signaux' }))
    expect(readCheckoutIntent()).toBeNull()
  })

  it('une intention ne survit pas à une seconde page de succès', async () => {
    saveCheckoutIntent('sig_locked_1')
    mockApi({ 'GET /billing/status': { body: PRO_STATUS } })
    const first = renderApp(<AppRoutes />, {
      session: AUTHENTICATED,
      route: '/checkout/success',
    })
    await screen.findByRole('link', { name: 'Revenir à ce signal' })
    first.unmount()

    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout/success' })
    expect(await screen.findByRole('link', { name: 'Accéder à mes signaux' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Revenir à ce signal' })).not.toBeInTheDocument()
  })
})
