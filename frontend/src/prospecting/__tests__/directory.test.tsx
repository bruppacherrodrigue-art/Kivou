import { fireEvent, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AUTHENTICATED, DISCOVERY_STATUS, ICP, callsTo, mockApi, renderApp } from '../../test/harness'
import { CompaniesPage } from '../../companies/CompaniesPage'
import { ProspectingProvider } from '../ProspectingProvider'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })
const capabilities = { can_view_company_data: false, can_enrich_company: false, can_lookup_contact: false, can_manage_personal_contact: true, can_take_notes: true, can_follow_company: true }
const row = { company_key: 'server-key', canonical_company_key: 'canonical', private_subject_key: 'private', name: 'Annuaire Entreprise', city: 'Toulouse', country: 'FR', tracked: false, capabilities,
  directory: { siren: '123456789', name: 'Annuaire Entreprise', city: 'Toulouse', naf_label: 'Construction', source: 'registre', removal_path: '/contact', fields_locked: true, available_fields: ['phone'] } }
const directoryPage = { items: [row], page: { limit: 20, next_cursor: null, has_more: false, scan_truncated: false }, counts: { total: 1, exact: true }, scope: null, read_at: 'now' }
const prospectPage = { items: [{ company_key: 'tracked-key', name: 'Entreprise suivie', city: 'Paris', country: 'FR', awards_count: 2, total_amount: [], last_award_at: null, contact_status: 'contacted', contacted_at: 'now', top_fit: null, tracked: true, origin: 'signal' }], page: { limit: 20, cursor: null, next_cursor: null, has_more: false, scan_truncated: false }, counts: { to_contact: 3, contacted: 4, replied: 1 }, counts_available: true, counts_truncated: false, total: 8, read_at: 'now', plan_code: 'discovery' }
function setup(route: string, extra = {}) {
  mockApi({ 'GET /target-icps': { body: [ICP] }, 'GET /target-icps/options': { body: { zones: [], sectors: [] } }, 'GET /billing/status': { body: DISCOVERY_STATUS },
    'GET /companies/directory': { body: directoryPage }, 'GET /companies/directory/options': { body: { families: [{ key: 'construction', label: 'Construction et travaux' }], departments: [{ code: '31', label: 'Haute-Garonne' }] } }, 'GET /companies': { body: prospectPage }, ...extra })
  return renderApp(<ProspectingProvider><Routes><Route path="/app/companies" element={<CompaniesPage />} /><Route path="/app/companies/directory" element={<CompaniesPage />} /><Route path="/app/companies/:companyKey" element={<CompaniesPage />} /></Routes></ProspectingProvider>, { session: AUTHENTICATED, route })
}

describe('one company table, two server lists', () => {
  it('resumes first-page refresh after loading more and changing filters', async () => {
    let calls = 0
    setup('/app/companies/directory', {
      'GET /companies/directory': () => {
        calls += 1
        if (calls === 1) return { body: { ...directoryPage, page: { ...directoryPage.page, next_cursor: 'page2', has_more: true } } }
        if (calls === 2) return { body: { ...directoryPage, items: [{ ...row, company_key: 'second', name: 'Deuxième page' }] } }
        return { body: calls === 3 ? directoryPage : {
          ...directoryPage, items: [row, { ...row, company_key: 'new-key', name: 'Nouvelle entreprise enrichie' }],
          counts: { total: 2, exact: true },
        } }
      },
    })
    await screen.findByRole('link', { name: 'Annuaire Entreprise' })
    fireEvent.click(screen.getByRole('button', { name: 'Charger plus' }))
    await screen.findByRole('link', { name: 'Deuxième page' })
    fireEvent.change(screen.getByLabelText('Trier les résultats'), { target: { value: 'city' } })
    await waitFor(() => expect(calls).toBe(3))
    expect(screen.queryByRole('link', { name: 'Deuxième page' })).not.toBeInTheDocument()
    fireEvent.focus(window)
    await screen.findByRole('link', { name: 'Nouvelle entreprise enrichie' })
    expect(screen.getByText('2 entreprises')).toBeInTheDocument()
    expect(callsTo('/companies/directory', 'GET').at(-1)!.search.get('sort')).toBe('city')
  })

  it('refreshes new catalogue rows and the count on return without losing URL filters', async () => {
    let calls = 0
    setup('/app/companies/directory?department=31&sort=city', {
      'GET /companies/directory': () => ({ body: ++calls === 1 ? directoryPage : {
        ...directoryPage, items: [row, { ...row, company_key: 'new-key', name: 'Nouvelle entreprise enrichie' }],
        counts: { total: 2, exact: true },
      } }),
    })
    await screen.findByRole('link', { name: 'Annuaire Entreprise' })
    fireEvent.focus(window)
    await screen.findByRole('link', { name: 'Nouvelle entreprise enrichie' })
    expect(screen.getByText('2 entreprises')).toBeInTheDocument()
    const query = callsTo('/companies/directory', 'GET').at(-1)!.search
    expect(query.get('department')).toBe('31')
    expect(query.get('sort')).toBe('city')
  })

  it('uses server labels for directory families and departments, sending only their codes', async () => {
    setup('/app/companies/directory')
    await screen.findByRole('link', { name: 'Annuaire Entreprise' })
    fireEvent.click(screen.getByRole('button', { name: 'Filtres' }))
    expect(await screen.findByRole('option', { name: 'Construction et travaux' })).toHaveValue('construction')
    fireEvent.change(screen.getByLabelText('Famille d’activité'), { target: { value: 'construction' } })
    await waitFor(() => expect(callsTo('/companies/directory', 'GET').at(-1)?.search.get('family')).toBe('construction'))
    fireEvent.change(screen.getByLabelText('Département du siège'), { target: { value: '31' } })
    await waitFor(() => expect(callsTo('/companies/directory', 'GET').at(-1)?.search.get('department')).toBe('31'))
    expect(callsTo('/companies/directory/options', 'GET')).toHaveLength(1)
  })
  it('uses server counts without scanning every status and changes view to directory', async () => {
    setup('/app/companies')
    await screen.findByRole('link', { name: 'Entreprise suivie' })
    expect(callsTo('/companies', 'GET')).toHaveLength(1)
    expect(screen.getByText('8 entreprises')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Annuaire' }))
    await screen.findByRole('link', { name: 'Annuaire Entreprise' })
    expect(callsTo('/companies/directory', 'GET')).toHaveLength(1)
    expect(screen.getByRole('table')).toHaveAccessibleName('Entreprises')
    expect(screen.queryByText('Idée d’approche')).not.toBeInTheDocument()
  })

  it('sends directory search and sorting to the server rather than filtering a captured page', async () => {
    setup('/app/companies/directory')
    await screen.findByRole('link', { name: 'Annuaire Entreprise' })
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'béton' } })
    await waitFor(() => expect(callsTo('/companies/directory', 'GET').at(-1)?.search.get('q')).toBe('béton'))
    fireEvent.change(screen.getByLabelText('Trier les résultats'), { target: { value: 'city' } })
    await waitFor(() => expect(callsTo('/companies/directory', 'GET').at(-1)?.search.get('sort')).toBe('city'))
    expect(screen.getByRole('link', { name: 'Annuaire Entreprise' })).toHaveAttribute('href', expect.stringContaining('/app/companies/server-key'))
    expect(callsTo('/companies/server-key', 'GET')).toHaveLength(0)
  })

  it('appends the server cursor page once without four counting scans', async () => {
    setup('/app/companies/directory', { 'GET /companies/directory': ({ search }: { search: URLSearchParams }) => ({ body: search.get('cursor')
      ? { ...directoryPage, items: [{ ...row, company_key: 'second-key', name: 'Seconde entreprise' }], counts: { total: 2, exact: true } }
      : { ...directoryPage, counts: { total: 2, exact: true }, page: { ...directoryPage.page, next_cursor: 'opaque-cursor', has_more: true } } }) })
    await screen.findByRole('link', { name: 'Annuaire Entreprise' })
    fireEvent.click(screen.getByRole('button', { name: 'Charger plus' }))
    await screen.findByRole('link', { name: 'Seconde entreprise' })
    expect(screen.getByRole('link', { name: 'Annuaire Entreprise' })).toBeInTheDocument()
    expect(callsTo('/companies/directory', 'GET')).toHaveLength(2)
    expect(callsTo('/companies/directory', 'GET')[1].search.get('cursor')).toBe('opaque-cursor')
  })

  it('does not send a restricted prospecting search from a manual Discovery URL', async () => {
    setup('/app/companies?q=secret-search', { 'GET /billing/status': { body: { ...DISCOVERY_STATUS, entitlements: { ...DISCOVERY_STATUS.entitlements, filter_level: 'minimum' } } } })
    await screen.findByRole('link', { name: 'Entreprise suivie' })
    expect(screen.getByRole('searchbox')).toBeDisabled()
    expect(callsTo('/companies', 'GET')[0].search.has('q')).toBe(false)
    expect(screen.getByRole('searchbox')).toHaveValue('secret-search')
  })
})
