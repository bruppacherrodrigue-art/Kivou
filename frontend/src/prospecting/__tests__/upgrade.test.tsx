import { fireEvent, screen, waitFor } from '@testing-library/react'
import { useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AUTHENTICATED, CATALOGUE, DISCOVERY_STATUS, PRO_STATUS, callsTo, mockApi, renderApp } from '../../test/harness'
import { UpgradeDialog } from '../components/UpgradeDialog'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })
function Probe() { const location = useLocation(); return <output data-testid="route">{JSON.stringify({ path: location.pathname, search: location.search, state: location.state })}</output> }
describe('server catalogue upgrade invitation', () => {
  it('requires an explicit plan choice and carries the company intent without starting payment', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE }, 'GET /billing/status': { body: DISCOVERY_STATUS } })
    renderApp(<><UpgradeDialog onClose={vi.fn()} intent={{ kind: 'company', companyKey: 'requested-alias' }} /><Probe /></>, { session: AUTHENTICATED, route: '/app/companies/requested-alias' })
    fireEvent.click(await screen.findByRole('button', { name: 'Choisir Essentiel' }))
    expect(screen.getByTestId('route')).toHaveTextContent('"path":"/app/billing"')
    expect(screen.getByTestId('route')).toHaveTextContent('"checkoutIntent":{"kind":"company","companyKey":"requested-alias"}')
    expect(screen.getByTestId('route')).toHaveTextContent('"checkoutAccountId":"acc_1"')
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })
  it('does not offer a second subscription when the server requires management', async () => {
    mockApi({ 'GET /billing/plans': { body: CATALOGUE }, 'GET /billing/status': { body: { ...PRO_STATUS, billing_action: 'manage_subscription' } } })
    renderApp(<UpgradeDialog onClose={vi.fn()} intent={{ kind: 'signal', signalKey: 'signal' }} />, { session: AUTHENTICATED })
    await screen.findByRole('link', { name: 'Gérer ma facturation' })
    expect(screen.getByRole('heading', { name: 'Votre prospection, avec les bons accès.' })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Choisir Essentiel' })).not.toBeInTheDocument())
    expect(callsTo('/billing/checkout')).toHaveLength(0)
  })
})
