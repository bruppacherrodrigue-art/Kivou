import { render, screen, waitFor, within } from '@testing-library/react'
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
  },
  queue: { available: true, last_cycle_at: '2026-09-11T09:30:00Z', items: [] },
  directory: {
    summary: {
      company_count: 81,
      confirmed_domain_count: 35,
      verified_email_count: 16,
      reverification_required_count: 20,
    },
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
  render(
    <ProspectionPage
      data={READ_MODEL}
      filters={{ page: 1, q: '', family: '', department: '', status: '' }}
      refreshing={false}
      onFiltersChange={vi.fn()}
    />,
  )
}

afterEach(() => vi.unstubAllGlobals())

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
    let releaseSend!: (value: object) => void
    const sendResponse = new Promise<object>((resolve) => { releaseSend = resolve })
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) {
        return { ok: true, status: 200, json: async () => list([]) }
      }
      if (url.includes('/list?status=approved')) {
        return { ok: true, status: 200, json: async () => list(approved) }
      }
      if (url.endsWith('/send')) {
        const payload = await sendResponse
        return { ok: true, status: 200, json: async () => payload }
      }
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

    expect(screen.getByText('Envoi de 5 cibles…')).toBeInTheDocument()
    expect(screen.queryByRole('row', { name: /Entreprise 1/ })).not.toBeInTheDocument()
    const sendCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/send'))
    expect(JSON.parse(String(sendCall?.[1]?.body))).toEqual({
      request_id: requestId,
      targets: approved.map((item) => ({
        target_id: item.target_id,
        expected_version: item.version,
      })),
    })

    releaseSend({
      version: 'founder-prospection-actions-v1',
      request_id: requestId,
      results: approved.map((item, index) => ({
        target_id: item.target_id,
        status: 'sent',
        instantly_id: `fake-lead-${index + 1}`,
      })),
      daily_sent_count: 5,
      daily_remaining: 20,
    })
    expect(await screen.findByText('5 cibles envoyées.')).toBeInTheDocument()
  })

  it('réutilise le request_id lorsque le même lot est repris après une erreur ambiguë', async () => {
    const user = userEvent.setup()
    const approved = [target(1, 'approved')]
    const requestId = '162cc52c-650d-4866-bd7e-b505920f5eb5'
    const randomUUID = vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(requestId)
    let attempts = 0
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/list?status=pending_review')) {
        return { ok: true, status: 200, json: async () => list([]) }
      }
      if (url.includes('/list?status=approved')) {
        return { ok: true, status: 200, json: async () => list(approved) }
      }
      if (url.endsWith('/send')) {
        attempts += 1
        if (attempts === 1) {
          return {
            ok: false,
            status: 502,
            json: async () => ({
              detail: {
                code: 'INSTANTLY_SEND_FAILED',
                message: 'Résultat du fournisseur inconnu.',
                target_ids: [approved[0].target_id],
              },
            }),
          }
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({
            version: 'founder-prospection-actions-v1',
            request_id: requestId,
            results: [{
              target_id: approved[0].target_id,
              status: 'sent',
              instantly_id: 'fake-lead-retried',
            }],
            daily_sent_count: 1,
            daily_remaining: 24,
          }),
        }
      }
      throw new Error(`requête inattendue: ${url} ${init?.method ?? 'GET'}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Envoyer la cible validée' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Envoyer maintenant' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Résultat du fournisseur inconnu. (INSTANTLY_SEND_FAILED)')

    await user.click(screen.getByRole('button', { name: 'Envoyer la cible validée' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Envoyer maintenant' }))
    expect(await screen.findByText('1 cible envoyée.')).toBeInTheDocument()

    const sendBodies = fetchMock.mock.calls
      .filter(([url]) => String(url).endsWith('/send'))
      .map(([, init]) => JSON.parse(String(init?.body)))
    expect(sendBodies).toHaveLength(2)
    expect(sendBodies[0].request_id).toBe(requestId)
    expect(sendBodies[1].request_id).toBe(requestId)
    expect(randomUUID).toHaveBeenCalledTimes(1)
  })
})
