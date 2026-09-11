import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import type { CompanyListPage, CompanyProfile } from '../api/types'
import {
  AUTHENTICATED,
  COMPANY_PROFILE,
  UNLOCKED_ITEM,
  callsTo,
  mockApi,
  renderApp,
} from '../test/harness'

const item = {
  company_key: COMPANY_PROFILE.company_key,
  name: 'H. Hüther GmbH',
  city: 'München',
  country: 'DE',
  awards_count: 3,
  total_amount: [{ currency: 'EUR', value: '1240000.00' }],
  last_award_at: '2026-08-31',
  contact_status: 'to_contact' as const,
  contacted_at: null,
  top_fit: 'strong',
}

function page(overrides: Partial<CompanyListPage> = {}): CompanyListPage {
  return {
    items: [item],
    page: { limit: 20, cursor: null, next_cursor: null, has_more: false, scan_truncated: false },
    read_at: '2026-09-03',
    plan_code: 'pro',
    ...overrides,
  }
}

function routes(profile: CompanyProfile = COMPANY_PROFILE) {
  const selectedProfile = {
    ...profile,
    official_identity: { ...profile.official_identity, name: item.name },
  }
  return {
    'GET /companies': { body: page() },
    [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: selectedProfile },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_ITEM },
    [`POST /companies/${COMPANY_PROFILE.company_key}/contact`]: {
      body: { company_key: COMPANY_PROFILE.company_key, contact_status: 'contacted', contacted_at: '2026-09-03T12:00:00Z', updated_at: '2026-09-03T12:00:00Z' },
    },
    [`PUT /companies/${COMPANY_PROFILE.company_key}/note`]: {
      body: { company_key: COMPANY_PROFILE.company_key, note: 'À rappeler', updated_at: '2026-09-03T12:00:00Z' },
    },
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

afterEach(() => vi.unstubAllGlobals())

describe('CompaniesPage', () => {
  it('explique l’état vide avec le vocabulaire des titulaires', async () => {
    mockApi({ ...routes(), 'GET /companies': { body: page({ items: [] }) } })
    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })
    expect(await screen.findByText('Les titulaires de vos signaux apparaîtront ici.')).toBeVisible()
  })

  it('renders the CRM table from GET /companies', async () => {
    mockApi(routes())
    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { name: 'Entreprises' })).toBeInTheDocument()
    expect(screen.getByText('Les titulaires de vos signaux, avec où vous en êtes')).toBeInTheDocument()
    expect(await screen.findByText('H. Hüther GmbH')).toBeInTheDocument()
    expect(screen.getByText('München')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(callsTo('/signals', 'GET')).toHaveLength(0)
  })

  it('sends server-side status and search filters', async () => {
    mockApi(routes())
    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })
    const user = userEvent.setup()
    await screen.findByText('H. Hüther GmbH')

    await user.click(screen.getByRole('button', { name: /À contacter/ }))
    await user.type(screen.getByRole('searchbox'), 'bois')

    await waitFor(() => {
      const calls = callsTo('/companies', 'GET')
      expect(calls.some((call) => call.search.get('contact_status') === 'to_contact')).toBe(true)
      expect(calls.some((call) => call.search.get('q') === 'bois')).toBe(true)
    })
  })

  it('counts every page for each contact segment', async () => {
    const base = routes()
    mockApi({
      ...base,
      'GET /companies': (request) => {
        if (request.search.get('limit') !== '50') return { body: page() }
        if (request.search.get('contact_status') !== 'contacted') return { body: page() }
        if (request.search.get('cursor') === 'second') {
          return { body: page({ page: { limit: 50, cursor: 'second', next_cursor: null, has_more: false, scan_truncated: false } }) }
        }
        return { body: page({ page: { limit: 50, cursor: null, next_cursor: 'second', has_more: true, scan_truncated: false } }) }
      },
    })
    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    expect(await screen.findByRole('button', { name: 'Contactées 2' })).toBeInTheDocument()
  })

  it('renders missing values and appends the next page without duplicates', async () => {
    const second = { ...item, company_key: 'cmp_second_company_1234', name: 'Deuxième SA', city: null, total_amount: [], last_award_at: null }
    mockApi({
      ...routes(),
      'GET /companies': (request) => request.search.get('cursor') === 'next'
        ? { body: page({ items: [item, second] }) }
        : { body: page({ page: { limit: 20, cursor: null, next_cursor: 'next', has_more: true, scan_truncated: false } }) },
    })
    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Charger plus' }))
    expect(await screen.findByText('Deuxième SA')).toBeInTheDocument()
    expect(screen.getAllByText('H. Hüther GmbH')).toHaveLength(1)
    expect(screen.queryByText('—')).not.toBeInTheDocument()
  })

  it.each([
    ['Marquer contactée', 'contacted', 'Contactées 2', 'Contactée'],
    ['A répondu', 'replied', 'Ont répondu 2', 'A répondu'],
  ] as const)('applique %s partout avant la réponse réseau', async (button, status, segment, history) => {
    const pending = deferred<{ body: object }>()
    mockApi({
      ...routes(),
      [`POST /companies/${COMPANY_PROFILE.company_key}/contact`]: () => pending.promise,
    })
    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })
    const user = userEvent.setup()
    await user.click(await screen.findByText('H. Hüther GmbH'))

    await user.click(await screen.findByRole('button', { name: button }))

    expect(screen.getByRole('button', { name: button })).toBeDisabled()
    expect(screen.getByRole('button', { name: button })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: segment })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'À contacter 0' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'H. Hüther GmbH' }).closest('tr')).toHaveTextContent(
      status === 'contacted' ? 'Contactées' : 'Ont répondu',
    )
    expect(screen.getByText(new RegExp(`^${history} ·`))).toBeInTheDocument()
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}/contact`)[0].body).toEqual({ status })

    await act(async () => {
      pending.resolve({
        body: {
          company_key: COMPANY_PROFILE.company_key,
          contact_status: status,
          contacted_at: '2026-09-03T12:00:00Z',
          updated_at: '2026-09-03T12:00:00Z',
        },
      })
      await pending.promise
    })
  })

  it('restaure la fiche, la ligne, les compteurs et l’historique si l’action échoue', async () => {
    const pending = deferred<{ body: object }>()
    mockApi({
      ...routes(),
      [`POST /companies/${COMPANY_PROFILE.company_key}/contact`]: () => pending.promise,
    })
    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })
    const user = userEvent.setup()
    await user.click(await screen.findByText('H. Hüther GmbH'))
    await user.click(await screen.findByRole('button', { name: 'Marquer contactée' }))
    await act(async () => {
      pending.reject(new Error('network down'))
      await pending.promise.catch(() => undefined)
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('Le statut n’a pas pu être mis à jour')
    expect(screen.getByRole('button', { name: 'À contacter 1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Contactées 1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'H. Hüther GmbH' }).closest('tr')).toHaveTextContent('À contacter')
    expect(screen.queryByText(/^Contactée ·/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Marquer contactée' })).not.toBeDisabled()
  })

  it('ne lance qu’une mutation si les deux statuts sont cliqués dans le même batch', async () => {
    const pending = deferred<{ body: object }>()
    mockApi({
      ...routes(),
      [`POST /companies/${COMPANY_PROFILE.company_key}/contact`]: () => pending.promise,
    })
    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })
    const user = userEvent.setup()
    await user.click(await screen.findByText('H. Hüther GmbH'))

    act(() => {
      screen.getByRole('button', { name: 'Marquer contactée' }).click()
      screen.getByRole('button', { name: 'A répondu' }).click()
    })

    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}/contact`)).toHaveLength(1)

    await act(async () => {
      pending.reject(new Error('network down'))
      await pending.promise.catch(() => undefined)
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('Le statut n’a pas pu être mis à jour')
    expect(screen.getByRole('button', { name: 'À contacter 1' })).toBeInTheDocument()
  })

  it('n’envoie rien quand le statut courant est cliqué', async () => {
    const contacted = { ...COMPANY_PROFILE, contact_status: 'contacted' as const }
    mockApi(routes(contacted))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    const button = await screen.findByRole('button', { name: 'Marquer contactée' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-pressed', 'true')
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}/contact`)).toHaveLength(0)
  })

  it('saves the note on blur and confirms persistence', async () => {
    mockApi(routes())
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })
    const user = userEvent.setup()
    const note = await screen.findByRole('textbox', { name: 'Notes' })
    await user.type(note, 'À rappeler')
    await user.tab()

    await screen.findByText('Enregistré')
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}/note`, 'PUT')[0].body).toEqual({ body: 'À rappeler' })
  })

  it('ajoute la note à l’historique avant sa réponse réseau', async () => {
    const pending = deferred<{ body: object }>()
    mockApi({
      ...routes(),
      [`PUT /companies/${COMPANY_PROFILE.company_key}/note`]: () => pending.promise,
    })
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })
    const user = userEvent.setup()
    const note = await screen.findByRole('textbox', { name: 'Notes' })
    await user.type(note, 'À rappeler')
    await user.tab()

    expect(screen.getByText(/^Note mise à jour ·/)).toBeInTheDocument()

    await act(async () => {
      pending.resolve({ body: { company_key: COMPANY_PROFILE.company_key, note: 'À rappeler', updated_at: '2026-09-03T12:00:00Z' } })
      await pending.promise
    })
  })

  it('formats a SIRET and refuses a non-HTTPS website', async () => {
    const unsafe: CompanyProfile = {
      ...COMPANY_PROFILE,
      official_identity: { ...COMPANY_PROFILE.official_identity, website_url: 'javascript:alert(1)' },
    }
    mockApi(routes(unsafe))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByText(/SIRET 123 456 789 00011/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Site ↗' })).not.toBeInTheDocument()
  })

  it('omet les segments d’identité absents et nomme un historique vide', async () => {
    const sparse: CompanyProfile = {
      ...COMPANY_PROFILE,
      city: null,
      history: [],
      official_identity: {
        ...COMPANY_PROFILE.official_identity,
        identifiers: [],
        website_url: null,
      },
    }
    mockApi(routes(sparse))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    const drawer = await screen.findByRole('complementary', { name: 'H. Hüther GmbH' })
    expect(drawer).not.toHaveTextContent('· —')
    expect(drawer).not.toHaveTextContent('—')
    expect(screen.getByText("Aucune action pour l'instant")).toBeInTheDocument()
  })

  it('opens a signal drawer above the company drawer', async () => {
    mockApi(routes({ ...COMPANY_PROFILE, signals: [UNLOCKED_ITEM] }))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })
    const user = userEvent.setup()
    await user.click(await screen.findByText('Voirie'))

    expect(screen.getAllByRole('complementary')).toHaveLength(2)
    expect(screen.getByRole('heading', { name: 'H. Hüther GmbH' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Voirie' })).toBeInTheDocument()
  })

  it('place les données du registre et la synthèse avant les marchés', async () => {
    const enriched: CompanyProfile = {
      ...COMPANY_PROFILE,
      directory: {
        siren: '123456789',
        name: 'Constructions Bertrand SA',
        naf_code: '42.11Z',
        family_labels: ['Travaux routiers'],
        department: '31',
        city: 'Villeneuve',
        employees: 48,
        website_url: 'https://constructions-bertrand.example/',
        directors: [{ name: 'Alice Martin', title: 'Présidente' }],
        source: 'registre',
        removal_path: '/contact',
      },
      market_summary: {
        first_award_at: '2024-01-10',
        awards_per_quarter: '1.5',
        median_amounts: [{ value: '240000', currency: 'EUR' }],
        consortium_share: '0.25',
        recurring_buyers: ['Commune de Villeneuve'],
        resolution: 'company_key',
        source: 'public_awards',
      },
    }
    mockApi(routes(enriched))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByText('NAF 42.11Z')).toBeVisible()
    expect(screen.getByText('Travaux routiers')).toBeVisible()
    expect(screen.getByText('48 salariés')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Site internet ↗' })).toHaveAttribute(
      'href',
      'https://constructions-bertrand.example/',
    )
    expect(screen.getByText('Alice Martin')).toBeVisible()
    expect(screen.getByText('Présidente')).toBeVisible()
    expect(screen.getByText('1,5 marché par trimestre')).toBeVisible()
    expect(screen.getByText('240 000 € de montant médian')).toBeVisible()
    const headings = screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent)
    expect(headings.indexOf('Identité')).toBeLessThan(headings.indexOf('Synthèse des marchés'))
    expect(headings.indexOf('Synthèse des marchés')).toBeLessThan(headings.indexOf('Ses marchés'))
  })

  it('ouvre une entreprise du circuit local depuis son SIREN', async () => {
    mockApi({
      ...routes(),
      'GET /companies/directory/331364729': {
        body: {
          directory: {
            siren: '331364729',
            name: 'Bétons du Midi',
            naf_code: '23.63Z',
            family_labels: ['Béton prêt à l’emploi'],
            department: '31',
            city: 'Toulouse',
            source: 'registre',
            removal_path: '/contact',
          },
          markets: [{
            market_id: 'award-1',
            title: 'Fourniture de béton',
            date: '2026-08-04',
            source: 'public_awards',
          }],
        },
      },
    })
    renderApp(<AppRoutes />, {
      route: '/app/companies/directory/331364729',
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { name: 'Bétons du Midi' })).toBeVisible()
    expect(screen.getByText('NAF 23.63Z')).toBeVisible()
    expect(screen.getByText('Fourniture de béton')).toBeVisible()
    expect(callsTo('/companies/directory/331364729', 'GET')).toHaveLength(1)
  })
})
