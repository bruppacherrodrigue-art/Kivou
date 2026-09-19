import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import { AUTHENTICATED, CATALOGUE, DISCOVERY_STATUS, ICP, LOCKED_DETAIL, LOCKED_ITEM, feedPage, mockApi, renderApp } from '../test/harness'
import { readCheckoutReturn } from './checkoutIntent'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })

const ROUTES = {
  'GET /billing/plans': { body: CATALOGUE },
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /target-icps': { body: [ICP] },
  'GET /target-icps/options': { body: { zones: [], sectors: [] } },
  'GET /signals': { body: feedPage([LOCKED_ITEM]) },
  'GET /signals/sig_locked_1': { body: { ...LOCKED_DETAIL, access: { ...LOCKED_DETAIL.access, upgrade_to: ['essential', 'pro'] } } },
}

const PROTECTED = ['Constructions Bertrand', '12345678900011', 'Réfection de la voirie', 'boamp.fr', '1240000', 'Travaux publics']

async function openPaywall() {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: new RegExp(LOCKED_ITEM.headline) }))
  await user.click(await screen.findByRole('button', { name: 'Accéder à ce signal' }))
  await screen.findByRole('heading', { name: 'Continuez votre prospection' })
  return user
}

describe('continuité du paywall vers Stripe', () => {
  it('ne mémorise rien avant le choix explicite d’un plan', async () => {
    mockApi(ROUTES)
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })
    await openPaywall()
    expect(readCheckoutReturn('acc_1')).toBeNull()
  })

  it('mémorise uniquement la clé du signal après création effective du checkout', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    mockApi({ ...ROUTES, 'POST /billing/checkout': { body: { checkout_url: 'https://checkout.stripe.test/cs_1', plan: 'pro', currency: 'eur' } } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals' })
    const user = await openPaywall()
    await user.click(screen.getByRole('button', { name: /Choisir Pro/ }))

    expect(readCheckoutReturn('acc_1')).toEqual({ kind: 'signal', signalKey: 'sig_locked_1' })
    expect(assign).toHaveBeenCalledWith('https://checkout.stripe.test/cs_1')
    const stored = sessionStorage.getItem('kivou.checkout-intent') ?? ''
    for (const value of PROTECTED) expect(stored).not.toContain(value)
  })

  it('ne laisse aucune intention orpheline si Stripe ne peut pas être ouvert', async () => {
    mockApi({ ...ROUTES, 'POST /billing/checkout': { status: 503, body: { detail: { code: 'billing_unavailable' } } } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals/sig_locked_1' })
    const user = await openPaywall()
    await user.click(screen.getByRole('button', { name: /Choisir Pro/ }))

    expect(await screen.findByRole('alert')).toBeVisible()
    expect(readCheckoutReturn('acc_1')).toBeNull()
  })

  it('refuse une destination non sécurisée sans perdre le contexte courant', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    mockApi({ ...ROUTES, 'POST /billing/checkout': { body: { checkout_url: 'http://checkout.invalid/cs_1', plan: 'pro', currency: 'eur' } } })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/signals/sig_locked_1' })
    const user = await openPaywall()
    await user.click(screen.getByRole('button', { name: /Choisir Pro/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('destination de paiement')
    expect(assign).not.toHaveBeenCalled()
    expect(readCheckoutReturn('acc_1')).toBeNull()
  })
})
