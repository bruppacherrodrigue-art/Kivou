import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CompanyDossierResponse } from '../../api/types'
import { AUTHENTICATED, DISCOVERY_STATUS, ICP, callsTo, mockApi, renderApp } from '../../test/harness'
import { ProspectingProvider } from '../ProspectingProvider'
import { CompanyDossier } from '../components/CompanyDossier'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); sessionStorage.clear() })
const dossier: CompanyDossierResponse = {
  company_key: 'addressed-alias', canonical_company_key: 'public-canonical', private_subject_key: 'isolated-private', identity_resolution: 'isolated',
  note: 'Contexte privé', note_revision: 3, note_updated_at: null,
  manual_contact: { contact: null, revision: 0, updated_at: null },
  membership: { tracked: false, tracked_at: null, revision: 0, origin: null },
  capabilities: { can_view_company_data: false, can_enrich_company: false, can_lookup_contact: false, can_manage_personal_contact: true, can_take_notes: true, can_follow_company: true },
  directory: { siren: '123456789', name: 'Entreprise test', city: 'Toulouse', naf_label: 'Construction', source: 'registre', removal_path: '/contact', available_fields: ['phone'], fields_locked: true },
  markets: [{ market_id: 'public-only', title: 'Marché public exact', source: 'public_awards', source_url: 'https://www.boamp.fr/avis/123' }],
  contact_status: 'to_contact', plan_code: 'discovery',
}
function setup(profile = dossier, directorySiren?: string, extra = {}) {
  let current = profile
  mockApi({
    'GET /target-icps': { body: [ICP] }, 'GET /target-icps/options': { body: { zones: [], sectors: [] } }, 'GET /billing/status': { body: DISCOVERY_STATUS },
    [`GET /companies/${profile.company_key}`]: () => ({ body: current }),
    'GET /companies/directory/123456789': () => ({ body: current }),
    [`PUT /companies/${profile.company_key}/note`]: ({ body }) => ({ body: { company_key: profile.company_key, note: (body as { body: string }).body, revision: 4, updated_at: '2026-09-13T10:00:00Z' } }),
    [`PUT /companies/${profile.company_key}/prospection`]: () => { current = { ...current, membership: { tracked: true, revision: 1, origin: 'user', tracked_at: 'now' } }; return { body: { company_key: profile.company_key, ...current.membership } } },
    ...extra,
  })
  return renderApp(<ProspectingProvider><CompanyDossier companyKey={directorySiren ? undefined : profile.company_key} directorySiren={directorySiren} onClose={() => {}} /></ProspectingProvider>, { session: AUTHENTICATED, route: '/app/companies/addressed-alias' })
}

describe('one server-backed company dossier', () => {
  it('refreshes public enrichment without closing or erasing an in-progress private contact', async () => {
    const available = { state: 'available' as const, can_refresh: true, added_fields: [], missing_fields: ['phone' as const] }
    const profile = { ...dossier, capabilities: { ...dossier.capabilities, can_view_company_data: true, can_enrich_company: true }, directory: { ...dossier.directory!, fields_locked: false }, directory_enrichment: available }
    let reads = 0
    let requested = false
    setup(profile, undefined, {
      'POST /companies/addressed-alias/directory-enrichment': () => { requested = true; return { body: { ...available, state: 'queued', queued: true, job_id: 'job-1' } } },
      'GET /companies/addressed-alias': () => { reads += 1; return { body: !requested ? profile : { ...profile, directory: { ...profile.directory, phone: '0144556677' }, directory_enrichment: { ...available, state: 'partial', outcome: 'enriched', added_fields: ['phone'], job_id: 'job-1' } } } },
    })
    await screen.findByRole('heading', { name: 'Entreprise test' })
    const initialReads = reads
    vi.useFakeTimers()
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Compléter la fiche entreprise' })) })
    fireEvent.click(screen.getByRole('button', { name: 'Ajouter un contact' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Nom du contact' }), { target: { value: 'Mon brouillon privé' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Email professionnel' }), { target: { value: 'prive@example.com' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
    expect(screen.getByRole('textbox', { name: 'Nom du contact' })).toHaveValue('Mon brouillon privé')
    expect(screen.getByRole('textbox', { name: 'Email professionnel' })).toHaveValue('prive@example.com')
    fireEvent.click(screen.getByRole('button', { name: 'Annuler' }))
    expect(screen.getByRole('link', { name: '0144556677' })).toBeInTheDocument()
    expect(reads).toBe(initialReads + 1)
    expect(callsTo('/companies/addressed-alias/manual-contact', 'PUT')).toHaveLength(0)
  })
  it('shows the published holder contact with its BOAMP attribution in the dossier', async () => {
    setup({ ...dossier, capabilities: { ...dossier.capabilities, can_view_company_data: true },
      directory: { ...dossier.directory!, fields_locked: false },
      public_contacts: [{ organization_name: 'Agence Toulouse', organization_ref: 'ORG-1', identifiers: [], source: 'boamp', source_notice_id: '26-123', source_url: 'https://www.boamp.fr/avis/26-123', observed_at: '2026-09-13T10:00:00Z', email: 'agence@example.com', phone: '0561000000' }],
      contacts_locked: false, available_contact_fields: ['email', 'phone'],
    } as CompanyDossierResponse)
    expect(await screen.findByRole('link', { name: 'agence@example.com' })).toHaveAttribute('href', 'mailto:agence@example.com')
    expect(screen.getByRole('link', { name: /BOAMP.*26-123/ })).toHaveAttribute('href', 'https://www.boamp.fr/avis/26-123')
    expect(screen.getByText('Agence Toulouse')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ajouter un contact' })).toBeInTheDocument()
  })
  it('attributes each public contact to its own evidence rather than the telephone source', async () => {
    setup({ ...dossier, capabilities: { ...dossier.capabilities, can_view_company_data: true },
      directory: { ...dossier.directory!, fields_locked: false, phone: '0144556677', phone_source: 'model', website_url: 'https://company.example.test/', website_source: 'registre', published_email: 'bonjour@example.test', published_email_source_url: 'https://company.example.test/contact' },
    })
    const email = await screen.findByRole('link', { name: 'bonjour@example.test' })
    expect(within(email.closest('dd')!).getByRole('link', { name: 'Publié sur le site de l’entreprise' })).toHaveAttribute('href', 'https://company.example.test/contact')
    const phone = screen.getByRole('link', { name: '0144556677' })
    expect(phone.closest('dd')).toHaveTextContent('Coordonnée identifiée · à vérifier')
    expect(email.closest('dd')).not.toHaveTextContent('à vérifier')
    expect(screen.queryByText('model')).not.toBeInTheDocument()
  })
  it('shows only real locked families and does not follow or enrich simply by opening', async () => {
    setup({ ...dossier, directory: { ...dossier.directory!, phone: '0199999999' } } as CompanyDossierResponse)
    await screen.findByRole('heading', { name: 'Entreprise test' })
    expect(screen.getByText('Téléphone disponible dans la fiche enrichie')).toBeInTheDocument()
    expect(screen.queryByText('Effectif disponible dans la fiche enrichie')).not.toBeInTheDocument()
    expect(screen.queryByText('0199999999')).not.toBeInTheDocument()
    expect(screen.queryByText(/idée d’approche/i)).not.toBeInTheDocument()
    expect(callsTo('/companies/addressed-alias/prospection', 'PUT')).toHaveLength(0)
    expect(callsTo('/companies/addressed-alias/contact-lookup')).toHaveLength(0)
    expect(screen.getByRole('link', { name: /Marché public exact/ })).toHaveAttribute('href', 'https://www.boamp.fr/avis/123')
  })

  it('never renders locked public contact values or personal names from a stale payload', async () => {
    setup({ ...dossier, public_contacts: [{ organization_name: 'Agence secrète', organization_ref: 'ORG-1', source: 'boamp', observed_at: '2026-09-13T10:00:00Z', email: 'hidden@artisan.fr', phone: '0561000000', contact_name: 'Nom confidentiel' }],
      contacts_locked: true, available_contact_fields: ['email'] })
    await screen.findByRole('heading', { name: 'Entreprise test' })
    expect(screen.queryByText('hidden@artisan.fr')).not.toBeInTheDocument()
    expect(screen.queryByText('Nom confidentiel')).not.toBeInTheDocument()
    expect(screen.getByText('Email disponible dans la fiche enrichie')).toBeInTheDocument()
  })

  it('persists the private note with the requested alias and revision, then follows only on click', async () => {
    setup()
    const notes = await screen.findByRole('textbox', { name: 'Vos notes sur cette entreprise' })
    await waitFor(() => expect(notes).toHaveValue('Contexte privé'))
    fireEvent.change(notes, { target: { value: 'Prochaine étape' } })
    await waitFor(() => expect(callsTo('/companies/addressed-alias/note', 'PUT')).toHaveLength(1))
    expect(callsTo('/companies/addressed-alias/note', 'PUT')[0].body).toEqual({ body: 'Prochaine étape', expected_revision: 3 })
    fireEvent.click(screen.getByRole('button', { name: 'Ajouter à ma prospection' }))
    await waitFor(() => expect(callsTo('/companies/addressed-alias/prospection', 'PUT')).toHaveLength(1))
    await screen.findByRole('button', { name: 'Marquer comme contactée' })
  })

  it('uses the directory response company key without synthesizing a cmp_directory identity', async () => {
    setup({ ...dossier, company_key: 'server-directory-address' }, '123456789')
    await screen.findByRole('heading', { name: 'Entreprise test' })
    await waitFor(() => expect(callsTo('/companies/server-directory-address', 'GET').length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: 'Ajouter à ma prospection' }))
    await waitFor(() => expect(callsTo('/companies/server-directory-address/prospection', 'PUT')).toHaveLength(1))
    expect(callsTo('/companies/cmp_directory_123456789/prospection', 'PUT')).toHaveLength(0)
  })

  it('removes previously visible Apollo contacts when the server reports suppression', async () => {
    setup({ ...dossier, capabilities: { ...dossier.capabilities, can_view_company_data: true, can_lookup_contact: true },
      directory: { ...dossier.directory!, fields_locked: false },
      contact_lookup: { state: 'ready', remaining: 3, monthly_quota: 5, source: 'apollo', removal_path: '/contact', can_refresh: true, contacts: [{ name: 'Alice Martin', title: 'Achats', email: 'alice@example.test', email_status: 'verified' }] },
    }, undefined, { 'POST /companies/addressed-alias/contact-lookup': { status: 409, body: { detail: { code: 'contact_lookup_suppressed' } } } })
    await screen.findByText('alice@example.test')
    fireEvent.click(screen.getByRole('button', { name: 'Rechercher un contact' }))
    await waitFor(() => expect(screen.queryByText('alice@example.test')).not.toBeInTheDocument())
    expect(screen.queryByText('Alice Martin')).not.toBeInTheDocument()
  })
})
