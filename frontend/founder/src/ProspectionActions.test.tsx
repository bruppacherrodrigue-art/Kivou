import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProspectionPage } from './ProspectionPage'
import type {
  FounderProspection,
  FounderProspectionActionList,
  FounderProspectionActionTarget,
} from './types'

const READ_MODEL: FounderProspection = {
  version: 'founder-prospection-v1',
  generated_at: '2026-09-11T10:00:00Z',
  read_only: true,
  acquisition_status: {
    mode: 'ASSISTED',
    activity: 'RUNNING',
    activity_since: '2026-09-11T08:00:00Z',
    last_cycle_ref: 'cycle-qa',
    last_cycle_at: '2026-09-11T09:30:00Z',
    last_cycle_status: 'SUCCEEDED',
    last_cycle_reason_code: null,
    prepared_today_count: 3,
    daily_pending_cap: 25,
    next_run_at: '2026-09-11T11:00:00Z',
  },
  queue: { available: true, last_cycle_at: '2026-09-11T09:30:00Z', items: [] },
  directory: {
    summary: {
      company_count: 81,
      confirmed_domain_count: 35,
      verified_email_count: 16,
      reverification_required_count: 20,
    },
    enrichment: {
      enriched_today_count: 0,
      enriched_week_count: 0,
      model: null,
      cumulative_cost_usd: '0.000000',
      latest_batch_id: null,
      latest_batch_call_count: 0,
      latest_batch_input_tokens: 0,
      latest_batch_output_tokens: 0,
      latest_batch_cost_usd: '0',
      latest_batch_mean_input_tokens: null,
    },
    reverification_reason_counts: [],
    family_counts: [],
    department_counts: [],
    rows: [],
    pagination: { page: 1, page_size: 25, total_items: 0, total_pages: 0 },
  },
  targeting: null,
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

const TARGET: FounderProspectionActionTarget = {
  target_id: '5fca7822-e7d6-4f00-87a3-b9fec4b85063',
  version: 7,
  status: 'pending_review',
  company: {
    siren: '123456789',
    name: 'Béton des Alpes',
    city: 'Grenoble',
    employees: 31,
    family: 'Béton prêt à l’emploi',
  },
  director: { name: 'Sophie Durand', title: 'Présidente', source: 'registry' },
  email: {
    address: 'sophie@beton-alpes.example',
    source: 'apollo',
    verification_status: 'mx_verified',
  },
  signal: {
    opportunity_key: 'opp-qa',
    holder: 'Métropole de Grenoble',
    subject: 'Extension du réseau tramway',
    amount_minor_units: 120_000_000,
    currency: 'eur',
    location: 'Grenoble',
    decision_date: '2026-09-10',
  },
  mail: {
    subject: 'Extension du tramway — capacité béton',
    text: 'Bonjour Sophie,\n\nVoici le message préparé.',
    html: '<p>Bonjour Sophie,</p>',
    attribution_url: 'https://kivou.eu/a/token',
    unsubscribe_url: 'https://kivou.eu/unsubscribe/token',
    word_count: 7,
    contract_status: 'passed',
    contract_failure: null,
  },
  delivery: {
    status: 'not_sent',
    instantly_id: null,
    sent_at: null,
    opened_at: null,
    clicked_at: null,
    replied_at: null,
    bounced_at: null,
    unsubscribed_at: null,
    reply_classification: null,
    instantly_credit_units: 0,
    instantly_request_count: 0,
  },
  created_at: '2026-09-11T09:30:00Z',
  updated_at: '2026-09-11T09:30:00Z',
  approved_at: null,
  approved_by: null,
}

function list(items: FounderProspectionActionTarget[]): FounderProspectionActionList {
  return {
    version: 'founder-prospection-actions-v1',
    generated_at: '2026-09-11T10:00:00Z',
    daily_counts: { prepared: 1, approved: 0, rejected: 0, sent: 0 },
    daily_cap: 25,
    kill_switch_active: false,
    items,
    pagination: {
      page: 1,
      page_size: 25,
      total_items: items.length,
      total_pages: items.length === 0 ? 0 : 1,
    },
  }
}

function paginatedList(
  items: FounderProspectionActionTarget[],
  page: number,
  totalItems: number,
  totalPages: number,
): FounderProspectionActionList {
  return {
    ...list(items),
    pagination: {
      page,
      page_size: 25,
      total_items: totalItems,
      total_pages: totalPages,
    },
  }
}

function target(index: number, status: FounderProspectionActionTarget['status'] = 'pending_review') {
  const suffix = String(index).padStart(12, '0')
  return {
    ...TARGET,
    target_id: `5fca7822-e7d6-4f00-87a3-${suffix}`,
    version: 10 + index,
    status,
    company: { ...TARGET.company, name: `Entreprise ${index}` },
    email: { ...TARGET.email, address: `contact${index}@example.fr` },
  }
}

function renderPage() {
  return render(
    <ProspectionPage
      data={READ_MODEL}
      filters={{
        page: 1,
        q: '',
        family: '',
        department: '',
        status: '',
        reverification_reason: '',
      }}
      refreshing={false}
      onFiltersChange={vi.fn()}
      onRefresh={vi.fn()}
    />,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
  sessionStorage.clear()
})

describe('actions de prospection', () => {
  it('valide avec la version affichée et reflète la décision avant la réponse', async () => {
    const user = userEvent.setup()
    let releaseApprove!: (value: object) => void
    const approveResponse = new Promise<object>((resolve) => { releaseApprove = resolve })
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) {
        return { ok: true, status: 200, json: async () => list([TARGET]) }
      }
      if (url.includes('/list?status=approved')) {
        return { ok: true, status: 200, json: async () => list([]) }
      }
      if (url.endsWith('/approve')) {
        const payload = await approveResponse
        return { ok: true, status: 200, json: async () => payload }
      }
      throw new Error(`requête inattendue: ${url} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    const row = await screen.findByRole('row', { name: /Béton des Alpes/ })
    await user.click(within(row).getByRole('button', { name: 'Valider' }))

    expect(within(row).getByRole('button', { name: 'Validée' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Envoyer la cible validée' })).toBeEnabled()
    const approveCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/approve'))
    expect(approveCall).toBeDefined()
    expect(approveCall?.[1]).toEqual(expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ target_id: TARGET.target_id, expected_version: 7 }),
    }))

    releaseApprove({
      version: 'founder-prospection-actions-v1',
      target: {
        ...TARGET,
        version: 8,
        status: 'approved',
        approved_at: '2026-09-11T10:01:00Z',
        approved_by: 'rodrigue.bruppacher@gmail.com',
      },
    })
    await waitFor(() => expect(screen.getByText('1 cible validée')).toBeInTheDocument())
  })

  it('repart de la première page après validation pour ne pas masquer la 26e cible', async () => {
    const user = userEvent.setup()
    const pending = Array.from({ length: 26 }, (_, index) => target(index + 1))
    let approved = false
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = new URL(String(input), 'http://founder.test')
      if (url.pathname.endsWith('/list') && url.searchParams.get('status') === 'pending_review') {
        const items = approved ? pending.slice(1) : pending.slice(0, 25)
        return {
          ok: true,
          status: 200,
          json: async () => approved ? list(items) : paginatedList(items, 1, 26, 2),
        }
      }
      if (url.pathname.endsWith('/list') && url.searchParams.get('status') === 'approved') {
        const items = approved ? [{ ...pending[0], version: pending[0].version + 1, status: 'approved' as const }] : []
        return { ok: true, status: 200, json: async () => list(items) }
      }
      if (url.pathname.endsWith('/approve')) {
        approved = true
        return {
          ok: true,
          status: 200,
          json: async () => ({
            version: 'founder-prospection-actions-v1',
            target: { ...pending[0], version: pending[0].version + 1, status: 'approved' },
          }),
        }
      }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    const firstRow = await screen.findByRole('row', { name: /^Entreprise 1\b/ })
    await user.click(within(firstRow).getByRole('button', { name: 'Valider' }))

    expect(await screen.findByRole('row', { name: /Entreprise 26/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Charger la suite/ })).not.toBeInTheDocument()
  })

  it.each([
    [409, 'TARGET_VERSION_CONFLICT', 'La cible a été modifiée.'],
    [422, 'EMAIL_NOT_MX_VERIFIED', 'L’adresse n’a pas de MX vérifié.'],
    [502, 'INSTANTLY_SEND_FAILED', 'Instantly est indisponible.'],
  ])('affiche en clair une erreur %i et annule la mise à jour optimiste', async (status, code, message) => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) {
        return { ok: true, status: 200, json: async () => list([TARGET]) }
      }
      if (url.includes('/list?status=approved')) {
        return { ok: true, status: 200, json: async () => list([]) }
      }
      if (url.endsWith('/approve')) {
        return {
          ok: false,
          status,
          json: async () => ({ detail: { code, message, target_ids: [TARGET.target_id] } }),
        }
      }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    const row = await screen.findByRole('row', { name: /Béton des Alpes/ })
    await user.click(within(row).getByRole('button', { name: 'Valider' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(`${message} (${code})`)
    expect(within(row).getByRole('button', { name: 'Valider' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Envoyer les 0 cibles validées' })).toBeDisabled()
  })

  it('corrige adresse, dirigeant et nom avec la version affichée', async () => {
    const user = userEvent.setup()
    let releaseCorrection!: (value: object) => void
    const correctionResponse = new Promise<object>((resolve) => { releaseCorrection = resolve })
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) {
        return { ok: true, status: 200, json: async () => list([TARGET]) }
      }
      if (url.includes('/list?status=approved')) {
        return { ok: true, status: 200, json: async () => list([]) }
      }
      if (url.endsWith('/correct')) {
        const payload = await correctionResponse
        return { ok: true, status: 200, json: async () => payload }
      }
      throw new Error(`requête inattendue: ${url} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    const row = await screen.findByRole('row', { name: /Béton des Alpes/ })
    await user.click(within(row).getByRole('button', { name: 'Corriger' }))

    const drawer = screen.getByRole('dialog', { name: 'Corriger Béton des Alpes' })
    const company = within(drawer).getByRole('textbox', { name: 'Nom de l’entreprise' })
    const director = within(drawer).getByRole('textbox', { name: 'Dirigeant' })
    const email = within(drawer).getByRole('textbox', { name: 'Adresse e-mail' })
    await user.clear(company)
    await user.type(company, 'Béton Alpes Services')
    await user.clear(director)
    await user.type(director, 'Alice Martin')
    await user.clear(email)
    await user.type(email, 'direction@beton-alpes.example')
    await user.click(within(drawer).getByRole('button', { name: 'Enregistrer les corrections' }))

    expect(screen.getByText('Béton Alpes Services')).toBeInTheDocument()
    expect(screen.getByText('Alice Martin')).toBeInTheDocument()
    expect(screen.getByText('direction@beton-alpes.example')).toBeInTheDocument()
    const correctionCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/correct'))
    expect(correctionCall?.[1]).toEqual(expect.objectContaining({ method: 'POST' }))
    expect(JSON.parse(String(correctionCall?.[1]?.body))).toEqual({
      target_id: TARGET.target_id,
      expected_version: 7,
      changes: {
        email_address: 'direction@beton-alpes.example',
        director_name: 'Alice Martin',
        company_name: 'Béton Alpes Services',
      },
    })

    const corrected = {
      ...TARGET,
      version: 8,
      company: { ...TARGET.company, name: 'Béton Alpes Services' },
      director: { ...TARGET.director!, name: 'Alice Martin', source: 'manual' as const },
      email: {
        ...TARGET.email,
        address: 'direction@beton-alpes.example',
        source: 'manual' as const,
      },
    }
    releaseCorrection({
      version: 'founder-prospection-actions-v1',
      target: corrected,
      token_reissued: true,
      email_reverified: true,
      directory_updated: true,
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('écarte avec un motif fermé et retire la cible avant la réponse', async () => {
    const user = userEvent.setup()
    let releaseRejection!: (value: object) => void
    const rejectionResponse = new Promise<object>((resolve) => { releaseRejection = resolve })
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) {
        return { ok: true, status: 200, json: async () => list([TARGET]) }
      }
      if (url.includes('/list?status=approved')) {
        return { ok: true, status: 200, json: async () => list([]) }
      }
      if (url.endsWith('/reject')) {
        const payload = await rejectionResponse
        return { ok: true, status: 200, json: async () => payload }
      }
      throw new Error(`requête inattendue: ${url} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    const row = await screen.findByRole('row', { name: /Béton des Alpes/ })
    await user.click(within(row).getByRole('button', { name: 'Écarter' }))

    const drawer = screen.getByRole('dialog', { name: 'Écarter Béton des Alpes' })
    const reason = within(drawer).getByRole('combobox', { name: 'Motif' })
    expect(within(reason).getAllByRole('option').map((option) => option.textContent)).toEqual([
      'Choisir un motif',
      'Mauvaise entreprise',
      'Mauvaise adresse',
      'Hors sujet',
      'Autre',
    ])
    await user.selectOptions(reason, 'wrong_address')
    await user.click(within(drawer).getByRole('button', { name: 'Confirmer l’écartement' }))

    expect(screen.queryByRole('row', { name: /Béton des Alpes/ })).not.toBeInTheDocument()
    const rejectCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/reject'))
    expect(JSON.parse(String(rejectCall?.[1]?.body))).toEqual({
      target_id: TARGET.target_id,
      expected_version: 7,
      reason: 'wrong_address',
    })

    releaseRejection({
      version: 'founder-prospection-actions-v1',
      target: { ...TARGET, version: 8, status: 'rejected' },
      directory_effect: 'email_invalidated',
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('repart de la première page après écartement pour ne pas masquer la 26e cible', async () => {
    const user = userEvent.setup()
    const pending = Array.from({ length: 26 }, (_, index) => target(index + 1))
    let rejected = false
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = new URL(String(input), 'http://founder.test')
      if (url.pathname.endsWith('/list') && url.searchParams.get('status') === 'pending_review') {
        const items = rejected ? pending.slice(1) : pending.slice(0, 25)
        return {
          ok: true,
          status: 200,
          json: async () => rejected ? list(items) : paginatedList(items, 1, 26, 2),
        }
      }
      if (url.pathname.endsWith('/list') && url.searchParams.get('status') === 'approved') {
        return { ok: true, status: 200, json: async () => list([]) }
      }
      if (url.pathname.endsWith('/reject')) {
        rejected = true
        return {
          ok: true,
          status: 200,
          json: async () => ({
            version: 'founder-prospection-actions-v1',
            target: { ...pending[0], version: pending[0].version + 1, status: 'rejected' },
            directory_effect: 'none',
          }),
        }
      }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    const firstRow = await screen.findByRole('row', { name: /^Entreprise 1\b/ })
    await user.click(within(firstRow).getByRole('button', { name: 'Écarter' }))
    const drawer = screen.getByRole('dialog', { name: 'Écarter Entreprise 1' })
    await user.selectOptions(within(drawer).getByRole('combobox', { name: 'Motif' }), 'off_topic')
    await user.click(within(drawer).getByRole('button', { name: 'Confirmer l’écartement' }))

    expect(await screen.findByRole('row', { name: /Entreprise 26/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Charger la suite/ })).not.toBeInTheDocument()
  })

  it('exige un commentaire pour le motif Autre', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) {
        return { ok: true, status: 200, json: async () => list([TARGET]) }
      }
      if (url.includes('/list?status=approved')) {
        return { ok: true, status: 200, json: async () => list([]) }
      }
      throw new Error(`requête inattendue: ${url}`)
    }))

    renderPage()
    const row = await screen.findByRole('row', { name: /Béton des Alpes/ })
    await user.click(within(row).getByRole('button', { name: 'Écarter' }))
    const drawer = screen.getByRole('dialog', { name: 'Écarter Béton des Alpes' })
    await user.selectOptions(within(drawer).getByRole('combobox', { name: 'Motif' }), 'other')
    const confirm = within(drawer).getByRole('button', { name: 'Confirmer l’écartement' })
    expect(confirm).toBeDisabled()
    await user.type(within(drawer).getByRole('textbox', { name: 'Commentaire (obligatoire)' }), 'Doublon de la cible voisine')
    expect(confirm).toBeEnabled()
  })

  it('bloque uniquement l’envoi lorsque le coupe-circuit est actif', async () => {
    const approved = [target(1, 'approved')]
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) {
        return { ok: true, status: 200, json: async () => list([]) }
      }
      if (url.includes('/list?status=approved')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ ...list(approved), kill_switch_active: true }),
        }
      }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByText('Envois suspendus par le coupe-circuit.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Envoyer la cible validée' })).toBeDisabled()
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/send'))).toBe(false)
  })

  it('envoie les cinq cibles validées avec un request_id après confirmation explicite', async () => {
    const user = userEvent.setup()
    const approved = Array.from({ length: 5 }, (_, index) => target(index + 1, 'approved'))
    const requestId = '9f4d4b62-4bda-4be5-96ec-e555ef098765'
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(requestId)
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) return { ok: true, status: 200, json: async () => list(approved) }
      if (url.endsWith('/send')) {
        return { ok: true, status: 202, json: async () => sendProgress({ request_id: requestId, total_count: 5 }) }
      }
      if (url.endsWith(`/send/${requestId}`)) return { ok: true, status: 200, json: async () => sendProgress({
        request_id: requestId,
        status: 'completed',
        total_count: 5,
        processed_count: 5,
        sent_count: 5,
        items: approved.map((item) => ({
          target_id: item.target_id,
          email_address: item.email.address,
          status: 'sent',
          error_code: null,
          error_message: null,
        })),
      }) }
      throw new Error(`requête inattendue: ${url} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    const sendButton = await screen.findByRole('button', { name: 'Envoyer les 5 cibles validées' })
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/send'))).toBe(false)
    await user.click(sendButton)

    const confirmation = screen.getByRole('dialog', { name: 'Confirmer l’envoi de 5 cibles' })
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/send'))).toBe(false)
    await user.click(within(confirmation).getByRole('button', { name: 'Envoyer maintenant' }))

    const sendCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/send'))
    expect(JSON.parse(String(sendCall?.[1]?.body))).toEqual({
      request_id: requestId,
      targets: approved.map((item) => ({
        target_id: item.target_id,
        expected_version: item.version,
      })),
    })

    expect(await screen.findByText('5/5 envoyées')).toBeInTheDocument()
  })

  it('sépare les boîtes grand public et ne transmet que les domaines professionnels', async () => {
    const user = userEvent.setup()
    const professional = target(1, 'approved')
    const gmail = {
      ...target(2, 'approved'),
      email: { ...TARGET.email, address: 'artisan@gmail.com' },
    }
    const orange = {
      ...target(3, 'approved'),
      email: { ...TARGET.email, address: 'artisan@orange.fr' },
    }
    const approved = [professional, gmail, orange]
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) {
        return { ok: true, status: 200, json: async () => list([]) }
      }
      if (url.includes('/list?status=approved')) {
        return { ok: true, status: 200, json: async () => list(approved) }
      }
      if (url.endsWith('/send')) {
        const body = JSON.parse(String(init?.body))
        return {
          ok: true,
          status: 200,
          json: async () => ({
            version: 'founder-prospection-actions-v1',
            request_id: body.request_id,
            results: [{ target_id: professional.target_id, status: 'sent', instantly_id: 'lead-pro' }],
            daily_sent_count: 1,
            daily_remaining: 24,
          }),
        }
      }
      throw new Error(`requête inattendue: ${url} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByText('2 boîtes grand public en attente')).toBeInTheDocument()
    expect(screen.getByText('3 cibles validées · 1 éligible · 2 en attente')).toBeInTheDocument()
    const sendButton = screen.getByRole('button', { name: 'Envoyer la cible professionnelle' })
    await user.click(sendButton)
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Envoyer maintenant' }))

    const sendCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/send'))
    expect(JSON.parse(String(sendCall?.[1]?.body)).targets).toEqual([{
      target_id: professional.target_id,
      expected_version: professional.version,
    }])
  })

  it('garde une erreur de transport ambiguë en vérification sans exposer le corps amont', async () => {
    const user = userEvent.setup()
    const approved = [target(1, 'approved')]
    const requestId = '162cc52c-650d-4866-bd7e-b505920f5eb5'
    const randomUUID = vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(requestId)
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) {
        return { ok: true, status: 200, json: async () => list([]) }
      }
      if (url.includes('/list?status=approved')) {
        return { ok: true, status: 200, json: async () => list(approved) }
      }
      if (url.includes('/prospection/send/')) {
        return { ok: true, status: 200, json: async () => sendProgress({ request_id: requestId, status: 'running' }) }
      }
      if (url.endsWith('/send')) {
        return {
          ok: false,
          status: 502,
          json: async () => ({ proxy_error: 'upstream response lost' }),
        }
      }
      throw new Error(`requête inattendue: ${url} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Envoyer la cible validée' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Envoyer maintenant' }))
    expect(screen.queryByText('upstream response lost')).not.toBeInTheDocument()
    expect(await screen.findByText('0/1 envoyées')).toBeInTheDocument()

    const sendBodies = fetchMock.mock.calls
      .filter(([url]) => String(url).endsWith('/send'))
      .map(([, init]) => JSON.parse(String(init?.body)))
    expect(sendBodies).toHaveLength(1)
    expect(sendBodies[0].request_id).toBe(requestId)
    expect(randomUUID).toHaveBeenCalledTimes(1)
  })

  it('réconcilie un envoi partiel puis crée une nouvelle requête pour la cible échouée', async () => {
    const user = userEvent.setup()
    const approved = [target(1, 'approved'), target(2, 'approved')]
    const firstRequestId = '18fc22c2-628d-4ca1-a934-8a546bcedfa3'
    const secondRequestId = '3bd1d445-a035-42f2-bc41-bd1e98f1bcbc'
    vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValueOnce(firstRequestId)
      .mockReturnValueOnce(secondRequestId)
    let firstAttemptFinished = false
    let resolveTerminalRefresh!: (value: FounderProspectionActionList) => void
    const terminalRefresh = new Promise<FounderProspectionActionList>((resolve) => { resolveTerminalRefresh = resolve })
    let sendAttempt = 0
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) {
        return { ok: true, status: 200, json: async () => list([]) }
      }
      if (url.includes('/list?status=approved')) {
        return {
          ok: true,
          status: 200,
          json: async () => firstAttemptFinished
            ? terminalRefresh
            : list(approved),
        }
      }
      if (url.endsWith('/send')) {
        sendAttempt += 1
        if (sendAttempt === 1) {
          firstAttemptFinished = true
          return {
            ok: true,
            status: 202,
            json: async () => sendProgress({
              request_id: firstRequestId,
              status: 'partial',
              total_count: 2,
              processed_count: 2,
              sent_count: 1,
              failed_count: 1,
              items: [
                { target_id: approved[0].target_id, email_address: approved[0].email.address, status: 'sent', error_code: null, error_message: null },
                { target_id: approved[1].target_id, email_address: approved[1].email.address, status: 'failed', error_code: 'SEND_FAILED', error_message: 'Échec public' },
              ],
            }),
          }
        }
        return {
          ok: true,
          status: 202,
          json: async () => sendProgress({
            request_id: secondRequestId,
            status: 'completed',
            total_count: 1,
            processed_count: 1,
            sent_count: 1,
            items: [{ target_id: approved[1].target_id, email_address: approved[1].email.address, status: 'sent', error_code: null, error_message: null }],
          }),
        }
      }
      throw new Error(`requête inattendue: ${url} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Envoyer les 2 cibles validées' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Envoyer maintenant' }))

    expect(await screen.findByText('1/2 envoyée · 1 en échec')).toBeInTheDocument()
    const staleFailedRow = await screen.findByRole('row', { name: /Entreprise 2/ })
    await waitFor(() => expect(within(staleFailedRow).getByRole('button', { name: 'Corriger' })).toBeDisabled())
    expect(within(staleFailedRow).getByRole('button', { name: 'Écarter' })).toBeDisabled()
    resolveTerminalRefresh(list([{ ...approved[1], version: approved[1].version + 1 }]))
    await waitFor(() => expect(within(screen.getByRole('row', { name: /Entreprise 2/ }))
      .getByRole('button', { name: 'Corriger' })).toBeEnabled())
    expect(within(screen.getByRole('row', { name: /Entreprise 2/ }))
      .getByRole('button', { name: 'Écarter' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Envoyer la cible validée' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Envoyer maintenant' }))
    await waitFor(() => expect(sendAttempt).toBe(2))

    const secondBody = JSON.parse(String(fetchMock.mock.calls
      .filter(([url]) => String(url).endsWith('/send'))[1][1]?.body))
    expect(secondBody).toEqual({
      request_id: secondRequestId,
      targets: [{
        target_id: approved[1].target_id,
        expected_version: approved[1].version + 1,
      }],
    })
  })

  it('réconcilie la première page après 25 envois et révèle la 26e cible sans curseur périmé', async () => {
    const user = userEvent.setup()
    const approved = Array.from({ length: 26 }, (_, index) => target(index + 1, 'approved'))
    const requestId = 'a2083564-a5ea-48c1-89ad-467db95d78d8'
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(requestId)
    let firstBatchSent = false
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = new URL(String(input), 'http://founder.test')
      if (url.pathname.endsWith('/list') && url.searchParams.get('status') === 'pending_review') {
        return { ok: true, status: 200, json: async () => list([]) }
      }
      if (url.pathname.endsWith('/list') && url.searchParams.get('status') === 'approved') {
        if (firstBatchSent) {
          return { ok: true, status: 200, json: async () => list([approved[25]]) }
        }
        return url.searchParams.get('page') === '2'
          ? { ok: true, status: 200, json: async () => paginatedList([approved[25]], 2, 26, 2) }
          : { ok: true, status: 200, json: async () => paginatedList(approved.slice(0, 25), 1, 26, 2) }
      }
      if (url.pathname.endsWith('/send')) {
        const body = JSON.parse(String(init?.body))
        firstBatchSent = true
        return {
          ok: true,
          status: 202,
          json: async () => sendProgress({
            request_id: requestId,
            status: 'completed',
            total_count: 25,
            processed_count: 25,
            sent_count: 25,
            items: body.targets.map((item: { target_id: string }) => ({
              target_id: item.target_id,
              email_address: approved.find((target) => target.target_id === item.target_id)?.email.address ?? 'unknown@example.fr',
              status: 'sent',
              error_code: null,
              error_message: null,
            })),
          }),
        }
      }
      throw new Error(`requête inattendue: ${url} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    const sendButton = await screen.findByRole('button', { name: 'Envoyer les 25 cibles validées' })
    expect(screen.getByText('25 cibles validées')).toBeInTheDocument()
    await user.click(sendButton)
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Envoyer maintenant' }))

    expect(await screen.findByText('25/25 envoyées')).toBeInTheDocument()
    expect(await screen.findByRole('row', { name: /Entreprise 26/ })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Envoyer la cible validée' })).toBeEnabled()
    const sentBody = JSON.parse(String(fetchMock.mock.calls.find(([url]) => String(url).endsWith('/send'))?.[1]?.body))
    expect(sentBody.targets).toHaveLength(25)
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('status=approved&page=2'))).toBe(false)
  })

  it('affiche la progression durable, les échecs publics et jamais les diagnostics fournisseur', async () => {
    const user = userEvent.setup()
    const approved = Array.from({ length: 21 }, (_, index) => target(index + 1, 'approved'))
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000001')
    let resolveProgress!: (value: object) => void
    const progress = new Promise<object>((resolve) => { resolveProgress = resolve })
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) return { ok: true, status: 200, json: async () => list(approved) }
      if (url.endsWith('/send')) {
        return {
          ok: true,
          status: 202,
          json: async () => sendProgress({ request_id: '00000000-0000-4000-8000-000000000001', total_count: 21 }),
        }
      }
      if (url.endsWith('/send/00000000-0000-4000-8000-000000000001')) return { ok: true, status: 200, json: async () => progress }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Envoyer les 21 cibles validées' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Envoyer maintenant' }))

    expect(await screen.findByText('0/21 envoyées')).toBeInTheDocument()
    expect(within(screen.getByRole('row', { name: /^Entreprise 1 Grenoble/ })).getByText('Validée, non transmise')).toBeInTheDocument()
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/send/00000000-0000-4000-8000-000000000001'))).toBe(true))
    await act(async () => { resolveProgress(sendProgress({
      request_id: '00000000-0000-4000-8000-000000000001',
      status: 'running',
      total_count: 21,
      processed_count: 7,
      sent_count: 7,
      failed_count: 0,
    })) })
    expect(await screen.findByText('7/21 envoyées')).toBeInTheDocument()

    // The following poll is scheduled only after the first GET settles.
    await new Promise((resolve) => window.setTimeout(resolve, 0))
  })

  it('reprend une requête stockée sans second POST et ne la supprime qu’après le rendu terminal', async () => {
    sessionStorage.setItem('founder-prospection-send-request-id', 'request-resume')
    const progress = sendProgress({
      request_id: 'request-resume',
      status: 'partial',
      total_count: 21,
      processed_count: 21,
      sent_count: 18,
      failed_count: 3,
      items: [{
        target_id: TARGET.target_id,
        email_address: 'invalid@example.fr',
        status: 'failed',
        error_code: 'INVALID_EMAIL',
        error_message: 'Adresse invalide',
        request: { result: 'provider-secret' },
        instantly_id: 'instantly-secret',
      }],
    })
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) return { ok: true, status: 200, json: async () => list([target(1, 'approved')]) }
      if (url.endsWith('/send/request-resume')) return { ok: true, status: 200, json: async () => progress }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByText('18/21 envoyées · 3 en échec')).toBeInTheDocument()
    expect(screen.getByText('invalid@example.fr — Adresse invalide')).toBeInTheDocument()
    expect(screen.queryByText(/provider-secret|instantly-secret/)).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/send'))).toBe(false)
    await waitFor(() => expect(sessionStorage.getItem('founder-prospection-send-request-id')).toBeNull())
  })

  it('n’envoie pas deux fois le même lot et distingue acceptation fournisseur et livraison SMTP', async () => {
    const user = userEvent.setup()
    const approved = [target(1, 'approved')]
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000002')
    const queued = sendProgress({ request_id: '00000000-0000-4000-8000-000000000002', total_count: 1 })
    const completed = sendProgress({
      request_id: '00000000-0000-4000-8000-000000000002',
      status: 'completed',
      total_count: 1,
      processed_count: 1,
      sent_count: 1,
      items: [{
        target_id: approved[0].target_id,
        email_address: approved[0].email.address,
        status: 'sent',
        error_code: null,
        error_message: null,
      }],
    })
    let progressCall = 0
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) return { ok: true, status: 200, json: async () => list(approved) }
      if (url.endsWith('/send')) return { ok: true, status: 202, json: async () => queued }
      if (url.endsWith('/send/00000000-0000-4000-8000-000000000002')) {
        progressCall += 1
        return { ok: true, status: 200, json: async () => completed }
      }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Envoyer la cible validée' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Envoyer maintenant' }))
    await waitFor(() => expect(progressCall).toBe(1))
    expect(await screen.findByText('1/1 envoyée')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Acceptation fournisseur' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Livraison SMTP' })).toBeInTheDocument()
    const row = screen.getByRole('row', { name: /Entreprise 1/ })
    expect(within(row).getByText('Acceptée')).toBeInTheDocument()
    expect(within(row).getByText('Non confirmée')).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/send'))).toHaveLength(1)
    expect(progressCall).toBe(1)
  })

  it('annule le polling au démontage et ne lance jamais deux GET simultanés', async () => {
    vi.useFakeTimers()
    sessionStorage.setItem('founder-prospection-send-request-id', 'request-polling')
    let resolveProgress!: (value: object) => void
    const pendingProgress = new Promise<object>((resolve) => { resolveProgress = resolve })
    let progressSignal: AbortSignal | undefined
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.endsWith('/send/request-polling')) {
        progressSignal = init?.signal ?? undefined
        return { ok: true, status: 200, json: async () => pendingProgress }
      }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    const page = renderPage()
    await act(async () => { await Promise.resolve() })
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/send/request-polling'))).toHaveLength(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(8_000) })
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/send/request-polling'))).toHaveLength(1)

    page.unmount()
    expect(progressSignal?.aborted).toBe(true)
    await act(async () => { resolveProgress(sendProgress({ request_id: 'request-polling', total_count: 1 })) })
  })

  it('persiste l’identifiant et ne poste qu’une fois pendant une soumission lente', async () => {
    const user = userEvent.setup()
    const approved = [target(1, 'approved')]
    const requestId = '00000000-0000-4000-8000-000000000003'
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(requestId)
    let resolvePost!: (value: object) => void
    const post = new Promise<object>((resolve) => { resolvePost = resolve })
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) return { ok: true, status: 200, json: async () => list(approved) }
      if (url.endsWith('/send')) return { ok: true, status: 202, json: async () => post }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Envoyer la cible validée' }))
    const confirm = within(screen.getByRole('dialog')).getByRole('button', { name: 'Envoyer maintenant' })
    await user.dblClick(confirm)

    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/send'))).toHaveLength(1)
    expect(sessionStorage.getItem('founder-prospection-send-request-id')).toBe(requestId)
    await act(async () => { resolvePost(sendProgress({ request_id: requestId })) })
  })

  it('reprend par GET après un démontage pendant le POST, sans second POST', async () => {
    const user = userEvent.setup()
    const approved = [target(1, 'approved')]
    const requestId = '00000000-0000-4000-8000-000000000004'
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(requestId)
    let resolvePost!: (value: object) => void
    const post = new Promise<object>((resolve) => { resolvePost = resolve })
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) return { ok: true, status: 200, json: async () => list(approved) }
      if (url.endsWith('/send')) return { ok: true, status: 202, json: async () => post }
      if (url.endsWith(`/send/${requestId}`)) return { ok: true, status: 200, json: async () => sendProgress({ request_id: requestId }) }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    const first = renderPage()
    await user.click(await screen.findByRole('button', { name: 'Envoyer la cible validée' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Envoyer maintenant' }))
    first.unmount()
    renderPage()

    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith(`/send/${requestId}`))).toBe(true))
    expect(await screen.findByText('0/1 envoyées')).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/send'))).toHaveLength(1)
    await act(async () => { resolvePost(sendProgress({ request_id: requestId, status: 'completed', total_count: 1, processed_count: 1, sent_count: 1 })) })
  })

  it('conserve l’overlay terminal lorsque la liste arrive ou se rafraîchit après la progression', async () => {
    sessionStorage.setItem('founder-prospection-send-request-id', 'request-overlay')
    let resolveApproved!: (value: FounderProspectionActionList) => void
    const firstApproved = new Promise<FounderProspectionActionList>((resolve) => { resolveApproved = resolve })
    let approvedLoads = 0
    const sentProgress = sendProgress({
      request_id: 'request-overlay', status: 'completed', total_count: 1, processed_count: 1, sent_count: 1,
      items: [{ target_id: TARGET.target_id, email_address: TARGET.email.address, status: 'sent', error_code: null, error_message: null }],
    })
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) {
        approvedLoads += 1
        return { ok: true, status: 200, json: async () => approvedLoads === 1 ? firstApproved : list([{ ...TARGET, status: 'approved' }]) }
      }
      if (url.endsWith('/send/request-overlay')) return { ok: true, status: 200, json: async () => sentProgress }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    const page = renderPage()
    expect(await screen.findByText('1/1 envoyée')).toBeInTheDocument()
    resolveApproved(list([{ ...TARGET, status: 'approved' }]))
    expect(await screen.findByText('Acceptée')).toBeInTheDocument()

    page.rerender(
      <ProspectionPage
        data={{ ...READ_MODEL, generated_at: '2026-09-11T10:01:00Z' }}
        filters={{ page: 1, q: '', family: '', department: '', status: '', reverification_reason: '' }}
        refreshing={false}
        onFiltersChange={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )
    expect(await screen.findByText('Acceptée')).toBeInTheDocument()
  })

  it('affiche l’erreur GET structurée et les éléments en vérification sans corps brut', async () => {
    sessionStorage.setItem('founder-prospection-send-request-id', 'request-structured')
    let getAttempt = 0
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.endsWith('/send/request-structured')) {
        getAttempt += 1
        return getAttempt === 1
          ? { ok: true, status: 200, json: async () => sendProgress({
              request_id: 'request-structured', status: 'waiting', total_count: 3, processed_count: 1, sent_count: 1,
              items: [
                { target_id: 'one', email_address: 'one@example.fr', status: 'sent', error_code: null, error_message: null },
                { target_id: 'two', email_address: 'two@example.fr', status: 'verification_pending', error_code: null, error_message: null },
                { target_id: 'three', email_address: 'three@example.fr', status: 'verification_pending', error_code: null, error_message: null },
              ],
            }) }
          : { ok: false, status: 404, json: async () => ({ detail: { code: 'SEND_REQUEST_NOT_FOUND', message: 'Requête introuvable', target_ids: [], result: 'secret' } }) }
      }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    expect(await screen.findByText('1/3 envoyée · 2 en vérification')).toBeInTheDocument()
    await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 2_050)) })
    expect(await screen.findByRole('alert')).toHaveTextContent('Requête introuvable (SEND_REQUEST_NOT_FOUND)')
    expect(screen.queryByText('secret')).not.toBeInTheDocument()
    expect(sessionStorage.getItem('founder-prospection-send-request-id')).toBeNull()
  })

  it('reprend en GET après un 504 ambigu sans autoriser un second POST', async () => {
    const user = userEvent.setup()
    const approved = [target(1, 'approved')]
    const requestId = '00000000-0000-4000-8000-000000000005'
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(requestId)
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) return { ok: true, status: 200, json: async () => list(approved) }
      if (url.endsWith('/send')) return { ok: false, status: 504, json: async () => ({ proxy_error: 'raw upstream body' }) }
      if (url.endsWith(`/send/${requestId}`)) return { ok: true, status: 200, json: async () => sendProgress({ request_id: requestId }) }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Envoyer la cible validée' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Envoyer maintenant' }))

    expect(await screen.findByText('0/1 envoyées')).toBeInTheDocument()
    expect(screen.queryByText('raw upstream body')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/send'))).toHaveLength(1)
  })

  it('applique la progression strictement au target_id quand deux cibles partagent un e-mail', async () => {
    sessionStorage.setItem('founder-prospection-send-request-id', 'request-duplicate-email')
    const first = target(1, 'approved')
    const second = { ...target(2, 'approved'), email: { ...TARGET.email, address: first.email.address } }
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) return { ok: true, status: 200, json: async () => list([first, second]) }
      if (url.endsWith('/send/request-duplicate-email')) return { ok: true, status: 200, json: async () => sendProgress({
        request_id: 'request-duplicate-email', status: 'completed', total_count: 2, processed_count: 1, sent_count: 1,
        items: [{ target_id: first.target_id, email_address: first.email.address, status: 'sent', error_code: null, error_message: null }],
      }) }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    const firstRow = await screen.findByRole('row', { name: /^Entreprise 1 Grenoble/ })
    const secondRow = screen.getByRole('row', { name: /^Entreprise 2 Grenoble/ })
    expect(within(firstRow).getByText('Acceptée')).toBeInTheDocument()
    expect(within(secondRow).getByText('Validée, non transmise')).toBeInTheDocument()
  })

  it('efface un avertissement de polling dès qu’un GET de progression réussit', async () => {
    vi.useFakeTimers()
    sessionStorage.setItem('founder-prospection-send-request-id', 'request-recover')
    let attempts = 0
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.endsWith('/send/request-recover')) {
        attempts += 1
        return attempts === 1
          ? { ok: false, status: 502, json: async () => ({ detail: { code: 'TEMPORARY', message: 'Indisponible' } }) }
          : { ok: true, status: 200, json: async () => sendProgress({ request_id: 'request-recover', status: 'running', total_count: 1, processed_count: 1, sent_count: 1 }) }
      }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    await act(async () => { await Promise.resolve() })
    expect(screen.getByRole('alert')).toHaveTextContent('Indisponible (TEMPORARY)')
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000) })
    expect(screen.getByText('1/1 envoyée')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('rejette une réponse GET associée à une autre requête sans modifier le stockage ni les lignes', async () => {
    const requestId = 'request-active'
    sessionStorage.setItem('founder-prospection-send-request-id', requestId)
    const approved = target(1, 'approved')
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) return { ok: true, status: 200, json: async () => list([approved]) }
      if (url.endsWith(`/send/${requestId}`)) return { ok: true, status: 200, json: async () => sendProgress({
        request_id: 'request-other', status: 'completed', total_count: 1, processed_count: 1, sent_count: 1,
        items: [{ target_id: approved.target_id, email_address: approved.email.address, status: 'sent', error_code: null, error_message: null }],
      }) }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('La progression reçue ne correspond pas à la requête en cours.')
    expect(sessionStorage.getItem('founder-prospection-send-request-id')).toBe(requestId)
    expect(within(screen.getByRole('row', { name: /Entreprise 1/ })).getByText('Validée, non transmise')).toBeInTheDocument()
    expect(screen.queryByText('1/1 envoyée')).not.toBeInTheDocument()
  })

  it('fusionne les réponses de progression partielles et garde les confirmations lors d’un rafraîchissement', async () => {
    vi.useFakeTimers()
    sessionStorage.setItem('founder-prospection-send-request-id', 'request-merge')
    const first = target(1, 'approved')
    const second = target(2, 'approved')
    let poll = 0
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) return { ok: true, status: 200, json: async () => list([]) }
      if (url.includes('/list?status=approved')) return { ok: true, status: 200, json: async () => list([first, second]) }
      if (url.endsWith('/send/request-merge')) {
        poll += 1
        return { ok: true, status: 200, json: async () => poll === 1
          ? sendProgress({ request_id: 'request-merge', status: 'running', total_count: 2, processed_count: 1, sent_count: 1,
              items: [{ target_id: first.target_id, email_address: first.email.address, status: 'sent', error_code: null, error_message: null }] })
          : sendProgress({ request_id: 'request-merge', status: 'partial', total_count: 2, processed_count: 2, sent_count: 1, failed_count: 1,
              items: [{ target_id: second.target_id, email_address: second.email.address, status: 'failed', error_code: 'INVALID', error_message: 'Adresse invalide' }] }) }
      }
      throw new Error(`requête inattendue: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    const page = renderPage()
    await act(async () => { await Promise.resolve() })
    expect(screen.getByText('1/2 envoyée')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000) })
    expect(screen.getByText('1/2 envoyée · 1 en échec')).toBeInTheDocument()
    expect(within(screen.getByRole('row', { name: /^Entreprise 1 Grenoble/ })).getByText('Acceptée')).toBeInTheDocument()

    page.rerender(
      <ProspectionPage
        data={{ ...READ_MODEL, generated_at: '2026-09-11T10:02:00Z' }}
        filters={{ page: 1, q: '', family: '', department: '', status: '', reverification_reason: '' }}
        refreshing={false}
        onFiltersChange={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )
    await act(async () => { await Promise.resolve() })
    expect(within(screen.getByRole('row', { name: /^Entreprise 1 Grenoble/ })).getByText('Acceptée')).toBeInTheDocument()
  })
})

function sendProgress(overrides: Record<string, unknown>) {
  return {
    version: 'founder-prospection-send-v2',
    request_id: 'request-default',
    status: 'queued',
    total_count: 1,
    processed_count: 0,
    sent_count: 0,
    failed_count: 0,
    status_url: '/api/founder/actions/prospection/send/request-default',
    items: [],
    ...overrides,
  }
}
