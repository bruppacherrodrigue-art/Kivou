import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { SignalsFeed } from '../../pages/SignalsFeed'
import { AUTHENTICATED, DISCOVERY_STATUS, ICP, PRO_STATUS, UNLOCKED_DETAIL, UNLOCKED_ITEM, mockApi, recordedCalls, renderApp } from '../../test/harness'
import { ProspectingProvider, useProspecting } from '../ProspectingProvider'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })
test('V11 signal list filters on the server and saves through the reversible workflow only', async () => {
  let status = 'new'
  let revision = 0
  mockApi({
    'GET /target-icps': { body: [ICP] }, 'GET /target-icps/options': { body: { zones: [], sectors: [] } },
    'GET /billing/status': { body: PRO_STATUS },
    'GET /signals': { body: { items: [{ ...UNLOCKED_ITEM, status, status_revision: revision }], counts_available: true, counts_truncated: false, counts: { new: 1, saved: 0, contacted: 0, ignored: 0 }, page: { has_more: false, scan_truncated: false }, history_access: { scope: 'grants_only', history_days: null } } },
    'PUT /signals/sig_unlocked_1/status': () => ({ body: { signal_id: 'sig_unlocked_1', status: status = 'saved', revision: ++revision, interaction: null, updated_at: '2026-09-13' } }),
  })
  renderApp(<ProspectingProvider><Routes><Route path="/app/signals" element={<SignalsFeed />} /></Routes></ProspectingProvider>, { session: AUTHENTICATED, route: '/app/signals?target_icp_id=icp_1' })
  expect(await screen.findByRole('heading', { name: 'Signaux' })).toBeInTheDocument()
  expect(await screen.findByRole('button', { name: 'Ouvrir : Voirie' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Sauvegarder le signal' }))
  await waitFor(() => expect(recordedCalls.some((call) => call.method === 'PUT' && call.url.endsWith('/status'))).toBe(true))
  const mutation = recordedCalls.find((call) => call.method === 'PUT')!
  expect(mutation.body).toEqual({ status: 'saved', expected_revision: 0 })
  expect(recordedCalls.some((call) => call.url.endsWith('/feedback'))).toBe(false)
  fireEvent.change(screen.getByRole('searchbox', { name: 'Rechercher un signal' }), { target: { value: 'béton' } })
  await waitFor(() => expect(recordedCalls.some((call) => call.url === '/signals' && call.search.get('q') === 'béton')).toBe(true))
  expect(recordedCalls.filter((call) => call.url === '/signals').every((call) => call.search.get('target_icp_id') === 'icp_1')).toBe(true)
})

const page = (available = true) => ({ items: [{ ...UNLOCKED_ITEM, status_revision: 0 }], counts_available: available, counts_truncated: available,
  counts: { new: available ? 12 : 0, saved: available ? 5 : 0, contacted: available ? 3 : 0 }, page: { has_more: available, next_cursor: available ? 'cursor-second' : null, scan_truncated: false } })
const profileRoutes = {
  'GET /target-icps': { body: [ICP, { ...ICP, target_icp_id: 'icp_2' }] },
  'GET /target-icps/options': { body: { zones: [], sectors: [] } },
  'GET /billing/status': { body: PRO_STATUS },
}
function NavigationProbe({ jump = '' }: { jump?: string }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { refreshAccess } = useProspecting()
  return <><output data-testid="location">{location.pathname}{location.search}</output><button onClick={() => navigate(jump)}>Change test context</button><button onClick={() => { void refreshAccess() }}>Refresh test access</button></>
}
function renderFeed(route: string, jump = '') {
  return renderApp(<ProspectingProvider><NavigationProbe jump={jump} /><Routes>
    <Route path="/app/signals" element={<SignalsFeed />} /><Route path="/app/signals/:signalKey" element={<SignalsFeed />} />
  </Routes></ProspectingProvider>, { session: AUTHENTICATED, route })
}

test('real Discovery rejects search from both the URL and the disabled control', async () => {
  mockApi({ ...profileRoutes,
    'GET /billing/status': { body: { ...DISCOVERY_STATUS, entitlements: { ...DISCOVERY_STATUS.entitlements, filter_level: 'minimum' } } },
    'GET /signals': { body: page() },
  })
  renderFeed('/app/signals?target_icp_id=icp_1&q=secret&cursor=old-search-page')
  expect(await screen.findByRole('button', { name: 'Ouvrir : Voirie' })).toBeInTheDocument()
  expect(screen.getByRole('searchbox', { name: 'Rechercher un signal' })).toBeDisabled()
  await waitFor(() => expect(screen.getByTestId('location')).not.toHaveTextContent('q=secret'))
  expect(recordedCalls.filter((call) => call.url === '/signals').every((call) => !call.search.has('q') && !call.search.has('cursor'))).toBe(true)
  expect(screen.getByText(/recherche.*abonnement/i)).toBeInTheDocument()
})

test('a downgrade clears paid URL search and its cursor before any new list request', async () => {
  let billing = PRO_STATUS
  mockApi({ ...profileRoutes, 'GET /billing/status': () => ({ body: billing }), 'GET /signals': { body: page() } })
  renderFeed('/app/signals?target_icp_id=icp_1&q=secret&cursor=paid-search-page')
  expect(await screen.findByRole('button', { name: 'Ouvrir : Voirie' })).toBeInTheDocument()
  expect(recordedCalls.some((call) => call.url === '/signals' && call.search.get('q') === 'secret')).toBe(true)
  const beforeDowngrade = recordedCalls.length
  billing = { ...DISCOVERY_STATUS, entitlements: { ...DISCOVERY_STATUS.entitlements, filter_level: 'minimum' } }
  fireEvent.click(screen.getByText('Refresh test access'))
  await waitFor(() => expect(screen.getByRole('searchbox', { name: 'Rechercher un signal' })).toBeDisabled())
  expect(await screen.findByRole('button', { name: 'Ouvrir : Voirie' })).toBeInTheDocument()
  const reloaded = recordedCalls.slice(beforeDowngrade).filter((call) => call.url === '/signals')
  expect(reloaded.length).toBeGreaterThan(0)
  expect(reloaded.every((call) => !call.search.has('q') && !call.search.has('cursor'))).toBe(true)
})

test('retains the first page global counts when the next page intentionally omits counts', async () => {
  mockApi({ ...profileRoutes, 'GET /signals': ({ search }) => ({ body: page(!search.has('cursor')) }) })
  renderFeed('/app/signals?target_icp_id=icp_1')
  expect(await screen.findByRole('tab', { name: /^Nouveaux\s*12\+$/ })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Page suivante' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Page suivante' })).toBeDisabled())
  expect(screen.getByRole('tab', { name: /^Nouveaux\s*12\+$/ })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: /^Sauvegardés\s*5\+$/ })).toBeInTheDocument()
})

test.each(['status=saved', 'q=other', 'sort=amount', 'target_icp_id=icp_2'])('does not reuse global counts after changing %s', async (change) => {
  mockApi({ ...profileRoutes, 'GET /signals': ({ search }) => ({ body: page(search.get('target_icp_id') === 'icp_1' && search.get('status') === 'new' && !search.has('q') && search.get('sort') === 'recent') }) })
  const jump = change.startsWith('target_icp_id') ? `/app/signals?${change}` : `/app/signals?target_icp_id=icp_1&${change}`
  renderFeed('/app/signals?target_icp_id=icp_1', jump)
  expect(await screen.findByRole('tab', { name: /^Nouveaux\s*12\+$/ })).toBeInTheDocument()
  fireEvent.click(screen.getByText('Change test context'))
  expect(await screen.findByRole('button', { name: 'Ouvrir : Voirie' })).toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole('tab', { name: 'Nouveaux' })).toBeInTheDocument())
  expect(screen.queryByRole('tab', { name: /^Nouveaux\s*12\+$/ })).not.toBeInTheDocument()
})

test('normalizes a legacy signal query to the canonical detail route retaining its artifact and context', async () => {
  mockApi({ ...profileRoutes, 'GET /signals': { body: page() },
    'GET /signals/sig_unlocked_1': { body: { ...UNLOCKED_DETAIL, status_revision: 0, company_key: null } },
    'GET /signals/sig_unlocked_1/note': { body: { note: null, revision: 0, updated_at: null } },
  })
  const artifact = 'a'.repeat(64)
  renderFeed(`/app/signals?signal=sig_unlocked_1&presentation_artifact_id=${artifact}&target_icp_id=icp_1&status=saved`)
  expect(await screen.findByRole('dialog', { name: 'Détail du signal' })).toBeInTheDocument()
  expect(screen.getByTestId('location')).toHaveTextContent('/app/signals/sig_unlocked_1?')
  expect(screen.getByTestId('location')).not.toHaveTextContent('signal=')
  await waitFor(() => expect(recordedCalls.some((call) => call.url === '/signals/sig_unlocked_1' && call.search.get('presentation_artifact_id') === artifact)).toBe(true))
  expect(screen.getByTestId('location')).toHaveTextContent('status=saved')
})
