import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { Route, Routes, useNavigate, type NavigateFunction } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { CompaniesPage } from '../../companies/CompaniesPage'
import { SignalsFeed } from '../../pages/SignalsFeed'
import { AUTHENTICATED, COMPANY_PROFILE, callsTo, feedPage, mockApi, renderApp, type RouteHandler } from '../../test/harness'
import { ProspectingProvider } from '../ProspectingProvider'
import { BASE, DETAIL, SIGNAL } from './signal-regression-harness'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })

const capabilities = { can_view_company_data: false, can_enrich_company: false, can_lookup_contact: false, can_manage_personal_contact: true, can_take_notes: true, can_follow_company: true }
const company = (key: string, name: string) => ({ company_key: key, canonical_company_key: key, private_subject_key: key, name, city: 'Toulouse', country: 'FR', tracked: false, origin: 'signal', capabilities,
  awards_count: 1, total_amount: [], last_award_at: null, contact_status: 'replied', contacted_at: null, top_fit: null,
  directory: { siren: '123456789', name, city: 'Toulouse', source: 'registre', removal_path: '/contact', fields_locked: true, available_fields: [] } })
const companyPage = (items: ReturnType<typeof company>[], cursor: string | null = null) => ({ items, total: 2, counts_available: true, counts_truncated: false,
  counts: { total: 2, exact: true, to_contact: 0, contacted: 0, replied: 2 }, scope: null, read_at: '2026-09-13', plan_code: 'pro',
  page: { limit: 20, cursor: null, next_cursor: cursor, has_more: cursor !== null, scan_truncated: false } })

test.each(['directory', 'prospection'] as const)('ignores delayed company pagination after a %s filter changes', async (mode) => {
  const directory = mode === 'directory'
  const path = directory ? '/companies/directory' : '/companies'
  const oldRow = company('old-company', 'Ancienne entreprise')
  const currentRow = company('current-company', 'Entreprise du filtre courant')
  let releaseOld!: (response: RouteHandler) => void
  const fetch = mockApi({ ...BASE,
    'GET /companies/directory/options': { body: { families: [], departments: [{ code: '31', label: 'Haute-Garonne' }] } },
    [`GET ${path}`]: ({ search }) => {
      if (search.get('cursor') === 'old-cursor') return new Promise<RouteHandler>((resolve) => { releaseOld = resolve })
      if (search.get('cursor') === 'current-cursor') return { body: companyPage([currentRow, company('current-second', 'Seconde entreprise courante')]) }
      const filtered = directory ? search.get('department') === '31' : search.get('contact_status') === 'replied'
      return { body: companyPage([filtered ? currentRow : oldRow], filtered ? 'current-cursor' : 'old-cursor') }
    },
  })
  renderApp(<ProspectingProvider><Routes><Route path="/app/companies/*" element={<CompaniesPage />} /></Routes></ProspectingProvider>, { session: AUTHENTICATED, route: `/app${path}` })
  await screen.findByRole('link', { name: oldRow.name })
  fireEvent.click(screen.getByRole('button', { name: 'Charger plus' }))
  await waitFor(() => expect(releaseOld).toBeDefined())
  const oldRequest = fetch.mock.calls.find(([url]) => new URL(String(url), 'http://localhost').searchParams.get('cursor') === 'old-cursor')!
  expect(oldRequest[1]?.signal?.aborted).toBe(false)

  fireEvent.click(screen.getByRole('button', { name: 'Filtres' }))
  const filter = screen.getByLabelText(directory ? 'Département du siège' : 'Suivi commercial')
  await waitFor(() => expect(filter).toBeEnabled())
  fireEvent.change(filter, { target: { value: directory ? '31' : 'replied' } })
  await screen.findByRole('link', { name: currentRow.name })
  expect(oldRequest[1]?.signal?.aborted).toBe(true)
  expect(screen.getByRole('button', { name: 'Charger plus' })).toBeEnabled()

  // The HTTP harness deliberately resolves aborted requests: the real page,
  // provider and transport must reject stale content rather than trust fetch.
  await act(async () => { releaseOld({ body: companyPage([oldRow, company('late-company', 'Entreprise périmée de page suivante')]) }) })
  expect(screen.queryByRole('link', { name: oldRow.name })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Entreprise périmée de page suivante' })).not.toBeInTheDocument()
  expect(screen.getAllByRole('link', { name: currentRow.name })).toHaveLength(1)
  expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(2)

  fireEvent.click(screen.getByRole('button', { name: 'Charger plus' }))
  await screen.findByRole('link', { name: 'Seconde entreprise courante' })
  expect(screen.getAllByRole('link', { name: currentRow.name })).toHaveLength(1)
  expect(callsTo(path, 'GET').map((call) => call.search.get('cursor'))).toEqual([null, 'old-cursor', null, 'current-cursor'])
  expect(screen.queryByRole('button', { name: 'Charger plus' })).not.toBeInTheDocument()
})

test('a late signal A response cannot replace signal B after route navigation', async () => {
  const b = { ...DETAIL, signal_id: 'signal-b', status: 'saved' as const, status_revision: 11, company_key: COMPANY_PROFILE.company_key,
    company: { ...DETAIL.company, name: 'Titulaire B' }, contract: { ...DETAIL.contract, lot_title: null, title: 'Marché B courant' },
    factual_display: { ...DETAIL.factual_display, object_short: 'Marché B courant' } }
  let releaseA!: (response: RouteHandler) => void
  let navigate!: NavigateFunction
  function NavigationDriver() { navigate = useNavigate(); return null }
  const fetch = mockApi({ ...BASE,
    'GET /signals': { body: feedPage([SIGNAL, b]) },
    [`GET /signals/${SIGNAL.signal_id}`]: () => new Promise<RouteHandler>((resolve) => { releaseA = resolve }),
    'GET /signals/signal-b': { body: b },
    'GET /signals/signal-b/note': { body: { note: 'Note privée B', revision: 3, updated_at: null } },
    [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: { ...COMPANY_PROFILE, capabilities } },
    'PUT /signals/signal-b/status': ({ body }) => ({ body: { signal_id: 'signal-b', status: (body as { status: string }).status, revision: 12, updated_at: null, interaction: null } }),
  })
  renderApp(<ProspectingProvider><NavigationDriver /><Routes>
    <Route path="/app/signals/:signalKey" element={<SignalsFeed />} />
  </Routes></ProspectingProvider>, { session: AUTHENTICATED, route: `/app/signals/${SIGNAL.signal_id}?target_icp_id=icp_1` })
  const firstDialog = await screen.findByRole('dialog', { name: 'Détail du signal' })
  expect(await within(firstDialog).findByRole('status')).toHaveTextContent('Chargement du signal')
  await waitFor(() => expect(releaseA).toBeDefined())
  const oldRequest = fetch.mock.calls.find(([url]) => String(url).startsWith(`/signals/${SIGNAL.signal_id}?`))!

  act(() => navigate('/app/signals/signal-b?target_icp_id=icp_1'))
  const dialog = await screen.findByRole('dialog', { name: 'Détail du signal' })
  await within(dialog).findByRole('heading', { name: 'Marché B courant' })
  await waitFor(() => expect(within(dialog).getByRole('textbox', { name: 'Vos notes sur ce signal' })).toHaveValue('Note privée B'))
  expect(oldRequest[1]?.signal?.aborted).toBe(true)

  await act(async () => { releaseA({ body: DETAIL }) })
  expect(within(dialog).getByRole('heading', { name: 'Marché B courant' })).toBeInTheDocument()
  expect(within(dialog).queryByRole('heading', { name: 'Voirie' })).not.toBeInTheDocument()
  expect(within(dialog).getByRole('textbox', { name: 'Vos notes sur ce signal' })).toHaveValue('Note privée B')
  expect(within(dialog).getByRole('link', { name: 'Titulaire B' })).toHaveAttribute('href', expect.stringContaining(`/app/companies/${COMPANY_PROFILE.company_key}`))
  expect(callsTo(`/signals/${SIGNAL.signal_id}/note`, 'GET')).toHaveLength(0)
  fireEvent.click(within(dialog).getByRole('button', { name: 'Retirer des sauvegardés' }))
  await waitFor(() => expect(callsTo('/signals/signal-b/status', 'PUT')).toHaveLength(1))
  expect(callsTo('/signals/signal-b/status', 'PUT')[0].body).toEqual({ status: 'new', expected_revision: 11 })
  expect(callsTo(`/signals/${SIGNAL.signal_id}/status`, 'PUT')).toHaveLength(0)
})
