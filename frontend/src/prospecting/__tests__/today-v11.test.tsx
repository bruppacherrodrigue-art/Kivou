import { screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { AppRoutes } from '../../App'
import { AUTHENTICATED, DASHBOARD, ICP, PRO_STATUS, UNLOCKED_ITEM, mockApi, recordedCalls, renderApp } from '../../test/harness'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })
test('Today uses selected scope, real weekly counters and company follow-up links', async () => {
  mockApi({
    'GET /target-icps': { body: [ICP] }, 'GET /target-icps/options': { body: { zones: [], sectors: [] } }, 'GET /billing/status': { body: PRO_STATUS },
    'GET /dashboard': { body: { ...DASHBOARD, week: { new: 7, saved: 3, contacted: 2, replied: 1 }, top3: [{ ...UNLOCKED_ITEM, status_revision: 0 }], to_follow_up: [{ company_key: 'cmp_follow', name: 'Entreprise suivie', last_signal: UNLOCKED_ITEM, days_since_contact: 8 }] } },
    'GET /companies': { body: { items: [], counts: { to_contact: 0, contacted: 0, replied: 1 }, counts_available: true, page: { has_more: false } } },
  })
  renderApp(<AppRoutes />, { session: AUTHENTICATED, route: '/app/dashboard?target_icp_id=icp_1' })
  expect(await screen.findByRole('heading', { name: 'Aujourd’hui' })).toBeInTheDocument()
  expect(await screen.findByRole('heading', { name: 'Vos priorités commerciales' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Entreprise suivie/ })).toHaveAttribute('href', expect.stringContaining('/app/companies/cmp_follow'))
  expect(screen.getByLabelText('Bilan de la semaine')).toHaveTextContent('7 nouveaux signaux')
  await waitFor(() => expect(recordedCalls.filter((call) => call.url === '/dashboard').every((call) => call.search.get('target_icp_id') === 'icp_1')).toBe(true))
  expect(screen.getAllByRole('button', { name: 'Ajuster' })).toHaveLength(1)
})
