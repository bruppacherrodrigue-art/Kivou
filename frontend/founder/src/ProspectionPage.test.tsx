import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FounderApp } from './FounderApp'
import type { FounderProspection, FounderSession } from './types'

const SESSION: FounderSession = {
  version: 'founder-session-v1',
  service: 'kivou-founder-control',
  environment: 'PRODUCTION',
  operator_email: 'rodrigue.bruppacher@gmail.com',
  read_only: true,
  generated_at: '2026-09-11T08:00:00Z',
}

const PROSPECTION: FounderProspection = {
  version: 'founder-prospection-v1',
  generated_at: '2026-09-11T08:00:00Z',
  read_only: true,
  timer: {
    state: 'STOPPED',
    unit: 'kivou-acquisition-production.timer',
    inactive_since: '2026-09-10T07:48:16Z',
    last_triggered_at: '2026-09-10T07:34:23Z',
    next_trigger_at: null,
  },
  queue: {
    available: false,
    last_cycle_at: '2026-09-10T11:46:00Z',
    items: [],
  },
  directory: {
    summary: {
      company_count: 81,
      confirmed_domain_count: 35,
      verified_email_count: 16,
      reverification_required_count: 20,
    },
    family_counts: [
      { key: 'subcontracted_structural_work', count: 29 },
      { key: 'reinforcement_steel', count: 27 },
      { key: 'ready_mix_concrete', count: 25 },
    ],
    department_counts: [
      { key: '69', count: 22 },
      { key: '38', count: 20 },
    ],
    rows: [
      {
        siren: '123456789',
        legal_name: 'Acier Rhône',
        family_keys: ['reinforcement_steel'],
        department: '69',
        city: 'Lyon',
        employees: 42,
        domain: 'acier-rhone.example',
        website_url: 'https://acier-rhone.example',
        confirmed_domain: true,
        professional_email: 'contact@acier-rhone.example',
        email_source: 'site',
        email_verification_status: 'VERIFIED',
        email_contact_name: 'Marie Martin',
        email_contact_title: 'Directrice générale',
        reverification_required_at: null,
        reverification_reason: null,
        updated_at: '2026-09-10T07:34:23Z',
      },
    ],
    pagination: { page: 1, page_size: 25, total_items: 81, total_pages: 4 },
  },
  targeting: {
    cycle_ref: 'cycle-1',
    status: 'SUPPRESSED',
    started_at: '2026-09-10T11:45:00Z',
    updated_at: '2026-09-10T11:46:00Z',
    completed_at: '2026-09-10T11:46:00Z',
    recent: true,
    signal: { title: 'Construction d’un centre technique', amount_minor_units: 84500000, currency: 'EUR' },
    family_keys: ['ready_mix_concrete', 'reinforcement_steel'],
    sirene_account_count: 75,
    confirmed_domain_count: 35,
    email_counts_by_level: [{ level: 1, count: 16 }],
    deviation_counts: [{ reason_code: 'contact_identity_unresolved', count: 5 }],
  },
  results: {
    sent_count: 0,
    opened_count: 0,
    attribution_click_count: 0,
    landing_count: 0,
    confirmed_profile_count: 0,
    paid_account_count: 0,
    mrr_by_currency: [],
    no_sends_yet: true,
  },
}

const PROSPECTION_WITH_QUEUE: FounderProspection = {
  ...PROSPECTION,
  queue: {
    available: true,
    last_cycle_at: '2026-09-11T07:45:00Z',
    items: [
      {
        target_ref: 'target-1',
        status: 'pending_review',
        company_name: 'Béton des Alpes',
        city: 'Grenoble',
        employees: 31,
        family_key: 'ready_mix_concrete',
        director_name: 'Sophie Durand',
        director_title: 'Présidente',
        email_address: 'sophie@beton-alpes.example',
        email_source: 'apollo',
        email_verification_status: 'VERIFIED',
        bait_holder: 'Métropole de Grenoble',
        bait_subject: 'Extension du réseau tramway',
        bait_amount_minor_units: 120000000,
        bait_currency: 'EUR',
        mail_subject: 'Extension du tramway — capacité béton',
        mail_body: 'Bonjour Sophie,\n\nVoici le message complet préparé pour cette cible.',
      },
    ],
  },
}

afterEach(() => {
  window.history.replaceState({}, '', '/')
  vi.unstubAllGlobals()
})

describe('ProspectionPage', () => {
  it('routes to the production directory and promotes it above the empty queue', async () => {
    window.history.replaceState({}, '', '/prospection')
    const fetchMock = vi.fn(async (input: string | URL | Request) => ({
      ok: true,
      status: 200,
      json: async () => (String(input).includes('/prospection') ? PROSPECTION : SESSION),
    }))
    vi.stubGlobal('fetch', fetchMock)

    render(<FounderApp />)

    expect(await screen.findByRole('heading', { name: 'Prospection' })).toBeInTheDocument()
    const navigation = screen.getByRole('navigation', { name: 'Navigation de la console' })
    expect(within(navigation).getAllByRole('link').map((link) => link.textContent)).toEqual([
      'Aujourd’hui',
      'Prospection',
      'Système',
    ])
    const counters = screen.getByLabelText('Compteurs de l’annuaire')
    expect(within(counters).getByText('81')).toBeInTheDocument()
    expect(within(counters).getByText('35')).toBeInTheDocument()
    expect(within(counters).getByText('16')).toBeInTheDocument()
    expect(within(counters).getByText('20')).toBeInTheDocument()
    expect(screen.getByText('Acier Rhône')).toBeInTheDocument()
    expect(screen.getByText(/Arrêté depuis le/)).toBeInTheDocument()
    expect(screen.getByText('Aucun envoi à ce jour.')).toBeInTheDocument()

    const annuaire = screen.getByRole('heading', { name: 'Annuaire' }).closest('section')
    const queue = screen.getByRole('heading', { name: 'File du jour' }).closest('section')
    expect(annuaire).not.toBeNull()
    expect(queue).not.toBeNull()
    expect(annuaire!.compareDocumentPosition(queue!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/founder/prospection?page=1&page_size=25',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/overview'))).toBe(false)
  })

  it('filters the directory and exposes the prepared mail without enabling assisted actions', async () => {
    const user = userEvent.setup()
    window.history.replaceState({}, '', '/prospection')
    const fetchMock = vi.fn(async (input: string | URL | Request) => ({
      ok: true,
      status: 200,
      json: async () => (String(input).includes('/prospection') ? PROSPECTION_WITH_QUEUE : SESSION),
    }))
    vi.stubGlobal('fetch', fetchMock)

    render(<FounderApp />)

    expect(await screen.findByText('Béton des Alpes')).toBeInTheDocument()
    const queue = screen.getByRole('heading', { name: 'File du jour' }).closest('section')
    const annuaire = screen.getByRole('heading', { name: 'Annuaire' }).closest('section')
    expect(queue).not.toBeNull()
    expect(annuaire).not.toBeNull()
    expect(queue!.compareDocumentPosition(annuaire!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    for (const name of ['Valider', 'Corriger', 'Écarter', 'Envoyer les 0 validées']) {
      const action = screen.getByRole('button', { name })
      expect(action).toBeDisabled()
      expect(action).toHaveAttribute('title', 'Disponible quand le mode assisté sera livré')
    }

    const mailButton = screen.getByRole('button', { name: 'Voir le mail de Béton des Alpes' })
    await user.click(mailButton)
    const drawer = screen.getByRole('dialog', { name: 'Mail préparé pour Béton des Alpes' })
    expect(drawer).not.toHaveAttribute('aria-modal')
    expect(within(drawer).getByText('Extension du tramway — capacité béton')).toBeInTheDocument()
    expect(within(drawer).getByText(/message complet préparé/)).toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: 'Fermer' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(mailButton).toHaveFocus()

    const family = screen.getByRole('combobox', { name: 'Famille' })
    await user.selectOptions(family, 'reinforcement_steel')
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('family=reinforcement_steel'),
      expect.objectContaining({ credentials: 'same-origin' }),
    ))

    const department = screen.getByRole('combobox', { name: 'Département' })
    await waitFor(() => expect(department).not.toBeDisabled())
    await user.selectOptions(department, '69')
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('department=69'),
      expect.objectContaining({ credentials: 'same-origin' }),
    ))

    const status = screen.getByRole('combobox', { name: 'Statut' })
    await waitFor(() => expect(status).not.toBeDisabled())
    await user.selectOptions(status, 'confirmed_domain')
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('status=confirmed_domain'),
      expect.objectContaining({ credentials: 'same-origin' }),
    ))

    const search = screen.getByRole('searchbox')
    await waitFor(() => expect(search).not.toBeDisabled())
    await user.type(search, 'acier & béton')
    await user.click(screen.getByRole('button', { name: 'Rechercher' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('q=acier+%26+b%C3%A9ton'),
      expect.objectContaining({ credentials: 'same-origin' }),
    ))

    const next = screen.getByRole('button', { name: 'Suivant' })
    await waitFor(() => expect(next).not.toBeDisabled())
    await user.click(next)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('page=2&page_size=25'),
      expect.objectContaining({ credentials: 'same-origin' }),
    ))
  })

  it('does not invent a stopped-since date when systemd has none', async () => {
    window.history.replaceState({}, '', '/prospection')
    const response: FounderProspection = {
      ...PROSPECTION,
      timer: { ...PROSPECTION.timer, inactive_since: null },
    }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => ({
      ok: true,
      status: 200,
      json: async () => (String(input).includes('/prospection') ? response : SESSION),
    })))

    render(<FounderApp />)

    expect(await screen.findByRole('heading', { name: 'Prospection' })).toBeInTheDocument()
    expect(screen.queryByText(/Arrêté depuis le/)).not.toBeInTheDocument()
    expect(screen.getByText('Arrêté')).toBeInTheDocument()
  })
})
