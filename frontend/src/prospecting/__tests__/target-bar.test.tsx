import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { AUTHENTICATED, ICP, PRO_STATUS, mockApi, recordedCalls, renderApp } from '../../test/harness'
import { ProspectingProvider } from '../ProspectingProvider'
import { TargetBar } from '../components/TargetBar'
import { useProspecting } from '../ProspectingProvider'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })
test('one target adjustment control applies consultation state without mutating the profile', async () => {
  mockApi({ 'GET /target-icps': { body: [ICP] }, 'GET /target-icps/options': { body: { zones: [{ code: 'FR-31', label: 'Haute-Garonne', country: 'FR' }], sectors: [] } }, 'GET /billing/status': { body: PRO_STATUS } })
  renderApp(<ProspectingProvider><TargetBar /></ProspectingProvider>, { session: AUTHENTICATED, route: '/app/signals' })
  expect(await screen.findByText(ICP.label)).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'Ajuster' })).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: 'Ajuster' }))
  fireEvent.change(screen.getByLabelText('Offre à privilégier'), { target: { value: 'materials_and_components' } })
  fireEvent.click(screen.getByRole('button', { name: 'Appliquer à ma consultation' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(recordedCalls.some((call) => call.method === 'PATCH')).toBe(false)
  expect(screen.getByText('Matériaux et composants')).toBeInTheDocument()
})

test('switching profile and refining offer zone and amount in one form preserves every explicit choice', async () => {
  const second = { ...ICP, target_icp_id: 'icp_2', label: 'Second profil', customer_input: { ...ICP.customer_input,
    offers: ['equipment_rental', 'materials_and_components'], secondary_offers: [], territories: ['FR'], territory_subdivisions: ['FR-31', 'FR-75'],
    minimum_contract_value: { minimum_amount: 100000, maximum_amount: null, currency: 'EUR' },
  } }
  mockApi({
    'GET /target-icps': { body: [ICP, second] },
    'GET /target-icps/options': { body: { zones: [{ code: 'FR-31', label: 'Haute-Garonne', country: 'FR' }, { code: 'FR-75', label: 'Paris', country: 'FR' }], sectors: [] } },
    'GET /billing/status': { body: PRO_STATUS },
  })
  function Query() { const p = useProspecting(); return <output data-testid="applied-query">{JSON.stringify(p.query)}</output> }
  renderApp(<ProspectingProvider><TargetBar /><Query /></ProspectingProvider>, { session: AUTHENTICATED, route: '/app/signals?target_icp_id=icp_1' })
  expect(await screen.findByText(ICP.label)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Ajuster' }))
  fireEvent.change(screen.getByLabelText('Profil cible'), { target: { value: 'icp_2' } })
  fireEvent.change(screen.getByLabelText('Offre à privilégier'), { target: { value: 'equipment_rental' } })
  fireEvent.change(screen.getByLabelText('Zone à privilégier'), { target: { value: 'FR-75' } })
  fireEvent.change(screen.getByLabelText('Montant minimum'), { target: { value: '250000.125' } })
  fireEvent.click(screen.getByRole('button', { name: 'Appliquer à ma consultation' }))
  await waitFor(() => expect(JSON.parse(screen.getByTestId('applied-query').textContent!)).toEqual({
    target_icp_id: 'icp_2', offer_category: 'equipment_rental', subdivision_code: 'FR-75', min_amount: '250000.125', amount_currency: 'EUR',
  }))
  expect(recordedCalls.some((call) => call.method === 'PATCH')).toBe(false)
})
