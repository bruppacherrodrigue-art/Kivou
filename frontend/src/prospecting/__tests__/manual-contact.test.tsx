import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { callsTo, mockApi } from '../../test/harness'
import { UserContactForm } from '../components/UserContactForm'

const context = vi.hoisted(() => ({ accountId: 'a', accessEpoch: 0, invalidate: vi.fn(), run: vi.fn(async (load: (signal: AbortSignal) => Promise<unknown>, signal?: AbortSignal) => load(signal ?? new AbortController().signal)) }))
vi.mock('../ProspectingProvider', () => ({ useProspecting: () => context }))
afterEach(() => vi.unstubAllGlobals())
const company = { company_key: 'private-alias', private_subject_key: 'private-subject', capabilities: { can_view_company_data: false, can_enrich_company: false, can_lookup_contact: false, can_manage_personal_contact: true, can_take_notes: true, can_follow_company: true } }
const initial = { contact: { name: 'Claire', role: 'Achats', email: 'claire@example.test', phone: null, source: 'user' as const }, revision: 2, updated_at: null }
const renderForm = (onSaved = vi.fn()) => render(<I18nProvider initialLocale="fr"><UserContactForm company={company} initial={initial} onCancel={() => {}} onSaved={onSaved} /></I18nProvider>)

describe('private manual contact form', () => {
  it('saves only after explicit submission, with the addressed alias and expected revision', async () => {
    mockApi({ 'PUT /companies/private-alias/manual-contact': { body: { ...initial, revision: 3 } } })
    const saved = vi.fn()
    renderForm(saved)
    expect(callsTo('/companies/private-alias/manual-contact', 'PUT')).toHaveLength(0)
    fireEvent.change(screen.getByLabelText('Nom du contact'), { target: { value: 'Clara' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enregistrer le contact' }))
    await waitFor(() => expect(saved).toHaveBeenCalledTimes(1))
    expect(callsTo('/companies/private-alias/manual-contact', 'PUT')[0].body).toEqual({ name: 'Clara', role: 'Achats', email: 'claire@example.test', phone: null, expected_revision: 2 })
  })

  it('keeps the draft after conflict and only overwrites after explicit comparison', async () => {
    let writes = 0
    mockApi({ 'PUT /companies/private-alias/manual-contact': () => ++writes === 1
      ? { status: 409, body: { detail: { code: 'manual_contact_conflict', contact: { ...initial.contact, name: 'Version serveur' }, revision: 6, updated_at: null } } }
      : { body: { ...initial, revision: 7 } } })
    renderForm()
    fireEvent.change(screen.getByLabelText('Nom du contact'), { target: { value: 'Mon brouillon' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enregistrer le contact' }))
    await screen.findByText('Version serveur')
    expect(screen.getByLabelText('Nom du contact')).toHaveValue('Mon brouillon')
    expect(writes).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: 'Enregistrer mes modifications' }))
    await waitFor(() => expect(writes).toBe(2))
    expect(callsTo('/companies/private-alias/manual-contact', 'PUT')[1].body).toMatchObject({ name: 'Mon brouillon', expected_revision: 6 })
  })

  it('requires a reachable contact and confirms revision-checked deletion', async () => {
    const fetch = mockApi({ 'DELETE /companies/private-alias/manual-contact': { body: { contact: null, revision: 3, updated_at: null } } })
    renderForm()
    fireEvent.change(screen.getByLabelText('Email professionnel'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enregistrer le contact' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('email ou un téléphone')
    fireEvent.click(screen.getByRole('button', { name: 'Supprimer ce contact' }))
    expect(fetch).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirmer la suppression' }))
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    expect(new Headers(fetch.mock.calls[0][1]?.headers).get('If-Match')).toBe('"2"')
  })
})
