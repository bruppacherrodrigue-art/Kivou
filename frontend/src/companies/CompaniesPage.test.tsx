import { screen, waitFor } from '@testing-library/react'
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
    [`POST /companies/${COMPANY_PROFILE.company_key}/contact`]: {
      body: { company_key: COMPANY_PROFILE.company_key, contact_status: 'contacted', contacted_at: '2026-09-03T12:00:00Z', updated_at: '2026-09-03T12:00:00Z' },
    },
    [`PUT /companies/${COMPANY_PROFILE.company_key}/note`]: {
      body: { company_key: COMPANY_PROFILE.company_key, note: 'À rappeler', updated_at: '2026-09-03T12:00:00Z' },
    },
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('CompaniesPage', () => {
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
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3)
  })

  it('opens the company drawer and performs both contact actions', async () => {
    mockApi(routes())
    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })
    const user = userEvent.setup()
    await user.click(await screen.findByText('H. Hüther GmbH'))

    expect(await screen.findByRole('complementary', { name: 'H. Hüther GmbH' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Marquer contactée' }))
    await user.click(screen.getByRole('button', { name: 'A répondu' }))

    const calls = callsTo(`/companies/${COMPANY_PROFILE.company_key}/contact`)
    expect(calls.map((call) => call.body)).toEqual([{ status: 'contacted' }, { status: 'replied' }])
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
})
