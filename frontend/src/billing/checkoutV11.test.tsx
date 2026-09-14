import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CheckoutSuccess } from '../pages/Checkout'
import { AppRoutes } from '../App'
import { CheckoutHandoff } from '../presentation/dashboard/CheckoutHandoff'
import { AUTHENTICATED, CATALOGUE, DISCOVERY_STATUS, ICP, ME, PRO_STATUS, callsTo, mockApi, recordedCalls, renderApp } from '../test/harness'
import { notifySignOutStarted } from '../api/client'
import { readCheckoutReturn, saveCheckoutReturn } from './checkoutIntent'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })
describe('V11 checkout access confirmation and return', () => {
  it('revalidates the company dossier on a cold success-page load without any previous prospecting provider', async () => {
    mockApi({ 'GET /billing/status': { body: PRO_STATUS }, 'GET /me': { body: ME },
      'GET /target-icps': { body: [ICP] }, 'GET /target-icps/options': { body: { zones: [], sectors: [] } },
      'GET /companies/addressed-alias': { status: 404, body: { detail: { code: 'company_not_found' } } },
    })
    saveCheckoutReturn(ME.account_id, { kind: 'company', companyKey: 'addressed-alias' })
    renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/checkout/success' })
    fireEvent.click(await screen.findByRole('link', { name: 'Revenir à cette entreprise' }))
    await screen.findByText('Cette entreprise n’est plus accessible.')
    expect(callsTo('/me', 'GET')).toHaveLength(1)
    expect(callsTo('/companies/addressed-alias', 'GET')).toHaveLength(1)
    expect(callsTo('/companies/addressed-alias', 'GET')[0].search.has('account_id')).toBe(false)
  })
  it('clears an abandoned intention when a generic checkout is explicitly opened', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    mockApi({ 'GET /billing/plans': { body: CATALOGUE }, 'GET /billing/status': { body: DISCOVERY_STATUS }, 'POST /billing/checkout': { body: { checkout_url: 'https://checkout.stripe.test/new-session' } } })
    saveCheckoutReturn(ME.account_id, { kind: 'company', companyKey: 'abandoned' })
    renderApp(<CheckoutHandoff />, { session: AUTHENTICATED, route: '/checkout?plan=pro' })
    fireEvent.click(await screen.findByRole('button', { name: 'Continuer vers Stripe' }))
    await waitFor(() => expect(assign).toHaveBeenCalledTimes(1))
    expect(readCheckoutReturn(ME.account_id)).toBeNull()
  })
  it('ignores an in-flight checkout destination as soon as logout starts', async () => {
    let release!: (value: { body: { checkout_url: string } }) => void
    const response = new Promise<{ body: { checkout_url: string } }>((resolve) => { release = resolve })
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    mockApi({ 'GET /billing/plans': { body: CATALOGUE }, 'GET /billing/status': { body: DISCOVERY_STATUS }, 'POST /billing/checkout': () => response })
    renderApp(<CheckoutHandoff />, { session: AUTHENTICATED, route: '/checkout?plan=pro' })
    fireEvent.click(await screen.findByRole('button', { name: 'Continuer vers Stripe' }))
    await waitFor(() => expect(callsTo('/billing/checkout')).toHaveLength(1))
    act(() => notifySignOutStarted())
    await act(async () => { release({ body: { checkout_url: 'https://checkout.stripe.test/session' } }); await response })
    expect(assign).not.toHaveBeenCalled()
  })
  it('awaits billing status then /me before offering the exact company return', async () => {
    let release!: (value: { body: typeof ME }) => void
    const meResponse = new Promise<{ body: typeof ME }>((resolve) => { release = resolve })
    mockApi({ 'GET /billing/status': { body: PRO_STATUS }, 'GET /me': () => meResponse })
    saveCheckoutReturn(ME.account_id, { kind: 'company', companyKey: 'addressed-alias' })
    renderApp(<CheckoutSuccess />, { session: AUTHENTICATED, route: '/checkout/success' })
    await waitFor(() => expect(callsTo('/me', 'GET')).toHaveLength(1))
    expect(screen.queryByRole('link', { name: 'Revenir à cette entreprise' })).not.toBeInTheDocument()
    release({ body: ME })
    expect(await screen.findByRole('link', { name: 'Revenir à cette entreprise' })).toHaveAttribute('href', '/app/companies/addressed-alias')
    expect(recordedCalls.slice(0, 2).map((call) => call.url)).toEqual(['/billing/status', '/me'])
  })
  it('does not confirm paid access when refreshing /me fails', async () => {
    mockApi({ 'GET /billing/status': { body: PRO_STATUS }, 'GET /me': { status: 503, body: {} } })
    renderApp(<CheckoutSuccess />, { session: AUTHENTICATED, route: '/checkout/success' })
    await waitFor(() => expect(callsTo('/me', 'GET')).toHaveLength(1))
    expect(screen.queryByRole('link', { name: 'Revenir à ce signal' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Réessayer la vérification' })).toBeInTheDocument()
  })
  it('never starts checkout when billing_action requires management even from a manual checkout URL', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE }, 'GET /billing/status': { body: PRO_STATUS } })
    renderApp(<CheckoutHandoff />, { session: AUTHENTICATED, route: '/checkout?plan=pro' })
    const link = await screen.findByRole('link', { name: 'Gérer ma facturation' })
    expect(link).toHaveAttribute('href', '/app/billing')
    const button = screen.queryByRole('button', { name: 'Continuer vers Stripe' })
    if (button) fireEvent.click(button)
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })
})
