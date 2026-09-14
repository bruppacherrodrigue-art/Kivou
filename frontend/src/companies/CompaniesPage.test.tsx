import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CompanyDossierResponse, CompanyProfile } from '../api/types'
import { AUTHENTICATED, COMPANY_PROFILE, ICP, PRO_STATUS, UNLOCKED_ITEM, callsTo, mockApi, renderApp } from '../test/harness'
import { ProspectingProvider } from '../prospecting/ProspectingProvider'
import { CompaniesPage } from './CompaniesPage'
import { DirectoryCompanyPage } from './DirectoryCompanyPage'

/* V11 migration: flags/static prices/optimistic-save assertions are retired.
 * Autosave/CAS/private alias guarantees also live in prospecting notes, dossier,
 * actions, enrichment and directory suites; every paid POST remains explicit. */
const key = COMPANY_PROFILE.company_key
const profile: CompanyDossierResponse & CompanyProfile = {
  ...COMPANY_PROFILE, canonical_company_key: key, private_subject_key: key, identity_resolution: 'resolved',
  note: null, note_revision: 0, note_updated_at: null,
  manual_contact: { contact: null, revision: 0, updated_at: null },
  membership: { tracked: true, tracked_at: '2026-09-01T00:00:00Z', revision: 1, origin: 'signal' },
  capabilities: { can_view_company_data: true, can_enrich_company: true, can_lookup_contact: true, can_manage_personal_contact: true, can_take_notes: true, can_follow_company: true },
  official_identity: { ...COMPANY_PROFILE.official_identity, name: 'Entreprise suivie' },
  signals: [], history: [], contact_status: 'to_contact',
  directory: { siren: '123456789', name: 'Entreprise suivie', city: 'Toulouse', naf_code: '42.11Z', naf_label: 'Travaux routiers', source: 'registre', removal_path: '/contact', fields_locked: false, available_fields: [], workforce: { minimum: 20, maximum: 49, precision: 'range' }, website_url: 'https://example.test/', directors: [{ name: 'Alice Martin', title: 'Présidente' }] },
  contact_lookup: { state: 'available', remaining: 20, monthly_quota: 20, source: 'apollo', removal_path: '/contact' },
}
function SignalProbe() { const location = useLocation(); return <output data-testid="signal-route">{location.pathname}{location.search}|{JSON.stringify(location.state)}</output> }
function setup(overrides: Partial<typeof profile> = {}, extra = {}, route = `/app/companies/${key}`) {
  let current = { ...profile, ...overrides }
  const row = () => ({ company_key: key, name: 'Entreprise suivie', city: current.city, country: 'FR', awards_count: 3, total_amount: [], last_award_at: null, contact_status: current.contact_status, contacted_at: current.contacted_at, top_fit: null, tracked: true, origin: 'signal' })
  mockApi({
    'GET /target-icps': { body: [ICP] }, 'GET /target-icps/options': { body: { zones: [], sectors: [] } }, 'GET /billing/status': { body: PRO_STATUS },
    'GET /companies': () => ({ body: { items: [row()], counts: { to_contact: 1, contacted: 0, replied: 0 }, counts_available: true, counts_truncated: false, total: 1, page: { limit: 20, next_cursor: null, has_more: false, scan_truncated: false }, read_at: 'now', plan_code: 'pro' } }),
    [`GET /companies/${key}`]: () => ({ body: current }),
    [`POST /companies/${key}/contact`]: ({ body }) => {
      current = { ...current, contact_status: (body as { status: typeof profile.contact_status }).status, contacted_at: '2026-09-13T12:00:00Z' }
      return { body: { company_key: key, contact_status: current.contact_status, contacted_at: current.contacted_at, updated_at: '2026-09-13T12:00:00Z' } }
    },
    [`PUT /companies/${key}/note`]: ({ body }) => ({ body: { company_key: key, note: (body as { body: string }).body, revision: 1, updated_at: '2026-09-13T12:00:00Z' } }),
    ...extra,
  })
  return renderApp(<ProspectingProvider><Routes><Route path="/app/companies" element={<CompaniesPage />} /><Route path="/app/companies/:companyKey" element={<CompaniesPage />} /><Route path="/app/companies/directory/:directorySiren" element={<DirectoryCompanyPage />} /><Route path="/app/signals/:signalKey" element={<SignalProbe />} /></Routes></ProspectingProvider>, { route, session: AUTHENTICATED })
}
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })

describe('CompaniesPage V11 business regressions', () => {
  it('preserves the server city and loads the company list, not a separate signal scan', async () => {
    setup({ city: 'MÜNCHEN' }, {}, '/app/companies')
    await screen.findByRole('link', { name: 'Entreprise suivie' })
    expect(screen.getByText('MÜNCHEN')).toBeInTheDocument()
    expect(callsTo('/companies', 'GET')).toHaveLength(1)
    expect(callsTo('/signals', 'GET')).toHaveLength(0)
  })

  it('sends paid search and commercial filters to the API', async () => {
    setup({}, {}, '/app/companies')
    await screen.findByRole('link', { name: 'Entreprise suivie' })
    fireEvent.click(screen.getByRole('button', { name: 'Filtres' }))
    fireEvent.change(screen.getByLabelText('Suivi commercial'), { target: { value: 'contacted' } })
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'bois' } })
    await waitFor(() => expect(callsTo('/companies', 'GET').at(-1)?.search.get('q')).toBe('bois'))
    expect(callsTo('/companies', 'GET').at(-1)?.search.get('contact_status')).toBe('contacted')
  })

  it.each(['contacted', 'replied', 'to_contact'] as const)('persists commercial transition %s from the server response', async (status) => {
    setup({ contact_status: status === 'to_contact' ? 'replied' : 'to_contact' })
    const select = await screen.findByLabelText('Statut commercial de Entreprise suivie')
    fireEvent.change(select, { target: { value: status } })
    await waitFor(() => expect(callsTo(`/companies/${key}/contact`)).toHaveLength(1))
    expect(callsTo(`/companies/${key}/contact`)[0].body).toEqual({ status })
    await waitFor(() => expect(screen.getByLabelText('Statut commercial de Entreprise suivie')).toHaveValue(status))
  })

  it('keeps the previous status on failure and prevents same-batch duplicate writes', async () => {
    let reject!: (reason: unknown) => void
    const pending = new Promise<{ body: object }>((_resolve, rejectPromise) => { reject = rejectPromise })
    setup({}, { [`POST /companies/${key}/contact`]: () => pending })
    const button = await screen.findByRole('button', { name: 'Marquer comme contactée' })
    act(() => { button.click(); button.click() })
    expect(callsTo(`/companies/${key}/contact`)).toHaveLength(1)
    expect(screen.getByLabelText('Statut commercial de Entreprise suivie')).toHaveValue('to_contact')
    await act(async () => { reject(new Error('offline')); await pending.catch(() => {}) })
    expect(await screen.findByRole('alert')).toHaveTextContent('L’action n’a pas été confirmée')
    expect(screen.getByRole('button', { name: 'Marquer comme contactée' })).toBeEnabled()
  })

  it('does not re-send the current commercial status', async () => {
    setup()
    const select = await screen.findByLabelText('Statut commercial de Entreprise suivie')
    fireEvent.change(select, { target: { value: 'to_contact' } })
    expect(callsTo(`/companies/${key}/contact`)).toHaveLength(0)
  })

  it('renders actual registry facts and refuses unsafe website URLs', async () => {
    setup({ directory: { ...profile.directory!, website_url: 'javascript:alert(1)' }, official_identity: { ...profile.official_identity, website_url: 'http://unsafe.example/' } })
    await screen.findByRole('heading', { name: 'Entreprise suivie' })
    expect(screen.getByText('20–49 salariés')).toBeInTheDocument()
    expect(screen.getByText(/Travaux routiers · 42.11Z/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /unsafe.example/ })).not.toBeInTheDocument()
    const headings = screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent)
    expect(headings).toEqual(expect.arrayContaining(['Contacts', 'Repères entreprise', 'Vos notes sur cette entreprise']))
  })

  it('preserves a real signal artifact and company return path in linked-publication navigation', async () => {
    const artifact = 'a'.repeat(64)
    setup({ signals: [{ ...UNLOCKED_ITEM, presentation: { ...UNLOCKED_ITEM.presentation!, artifact_id: artifact } }] })
    const heading = await screen.findByRole('heading', { name: 'Publications liées' })
    fireEvent.click(heading.closest('section')!.querySelector('a')!)
    const navigation = await screen.findByTestId('signal-route')
    expect(navigation).toHaveTextContent(`/app/signals/${UNLOCKED_ITEM.signal_id}`)
    expect(navigation).toHaveTextContent(`presentation_artifact_id=${artifact}`)
    expect(navigation).toHaveTextContent('returnToCompany')
  })

  it.each(['locked', 'identity_unavailable', 'quota_exhausted'] as const)('does not launch a lookup for server state %s', async (state) => {
    setup({ contact_lookup: { ...profile.contact_lookup!, state, remaining: state === 'identity_unavailable' ? 20 : 0, next_reset_at: '2026-10-01T00:00:00Z' }, capabilities: { ...profile.capabilities, can_lookup_contact: false } })
    await screen.findByRole('heading', { name: 'Entreprise suivie' })
    expect(screen.queryByRole('button', { name: 'Rechercher un contact' })).not.toBeInTheDocument()
    expect(callsTo(`/companies/${key}/contact-lookup`)).toHaveLength(0)
  })

  it('honors can_refresh rather than computing a local ninety-day permission', async () => {
    setup({ contact_lookup: { ...profile.contact_lookup!, state: 'ready', can_refresh: false, researched_at: '2020-01-01T00:00:00Z', contacts: [{ name: 'Alice', title: 'Achats', email: 'alice@example.test', email_status: 'verified' }] } })
    await screen.findByText('alice@example.test')
    expect(screen.queryByRole('button', { name: 'Rechercher un contact' })).not.toBeInTheDocument()
  })

  it('omits absent private identity facts without synthesizing identifiers or dates', async () => {
    setup({ directory: null, city: null, official_identity: { ...profile.official_identity, identifiers: [], address: null, website_url: null }, history: [] })
    await screen.findByRole('heading', { name: 'Entreprise suivie' })
    expect(screen.queryByText(/SIREN|SIRET/)).not.toBeInTheDocument()
    expect(screen.queryByText(/· —/)).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Historique du suivi' })).not.toBeInTheDocument()
  })
})
