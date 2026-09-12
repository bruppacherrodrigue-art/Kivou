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
    'GET /companies': {
      body: page({ signals_companies_v2_enabled: profile.company_profile_v2_enabled === true }),
    },
    [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: selectedProfile },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_ITEM },
    [`POST /companies/${COMPANY_PROFILE.company_key}/contact`]: {
      body: { company_key: COMPANY_PROFILE.company_key, contact_status: 'contacted', contacted_at: '2026-09-03T12:00:00Z', updated_at: '2026-09-03T12:00:00Z' },
    },
    [`POST /companies/${COMPANY_PROFILE.company_key}/contact-lookup`]: {
      body: {
        state: 'ready',
        remaining: 19,
        monthly_quota: 20,
        source: 'apollo',
        removal_path: '/contact',
        researched_at: '2026-09-11T09:00:00Z',
        refresh_after: '2026-12-10T09:00:00Z',
        can_refresh: false,
        organization: {
          employees: 84,
          website_url: 'https://holder.example/',
          phone: '+33 5 61 00 00 00',
          linkedin_url: 'https://www.linkedin.com/company/holder',
        },
        contacts: [{
          name: 'Alice Martin',
          title: 'Directrice commerciale',
          email: 'alice@holder.example',
          email_status: 'verified',
          linkedin_url: 'https://www.linkedin.com/in/alice-martin',
        }],
      },
    },
    [`PUT /companies/${COMPANY_PROFILE.company_key}/note`]: {
      body: { company_key: COMPANY_PROFILE.company_key, note: 'À rappeler', updated_at: '2026-09-03T12:00:00Z' },
    },
  }
}

function approvedProfile(overrides: Partial<CompanyProfile> = {}): CompanyProfile {
  return {
    ...COMPANY_PROFILE,
    company_profile_v2_enabled: true,
    plan_code: 'essential',
    directory: {
      siren: '481153435',
      name: 'ALYA BATIMENT',
      naf_code: '41.20A',
      naf_label: 'Construction de maisons individuelles',
      family_labels: ['Construction de bâtiments'],
      department: '69',
      department_label: 'Rhône',
      city: 'Belleville-en-Beaujolais',
      employees: 5,
      website_url: 'https://alya-batiment.example/',
      website_source: 'model',
      website_observed_at: '2026-09-11T09:00:00Z',
      directors: [{ name: 'Mosbah Benzaoui', title: 'Président' }],
      directors_observed_at: '2026-09-10T09:00:00Z',
      director_display_name: 'Mosbah Benzaoui',
      director_display_title: 'Président',
      phone: '+33 4 74 00 00 00',
      phone_source: 'model',
      phone_observed_at: '2026-09-11T09:00:00Z',
      published_email: 'contact@alya-batiment.example',
      published_email_source_url: 'https://alya-batiment.example/contact',
      published_email_observed_at: '2026-09-11T09:00:00Z',
      contact_observed_at: '2026-09-11T09:00:00Z',
      register_observed_at: '2026-09-10T09:00:00Z',
      source: 'registre',
      removal_path: '/contact',
    },
    market_summary: null,
    signals: [],
    history: [],
    note: null,
    contact_lookup: {
      state: 'available',
      remaining: 20,
      monthly_quota: 20,
      source: 'apollo',
      removal_path: '/contact',
    },
    ...overrides,
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
  it('conserve la ville historique quand le flag commun est désactivé', async () => {
    mockApi({
      ...routes(),
      'GET /companies': {
        body: page({ items: [{ ...item, city: 'MÜNCHEN' }], signals_companies_v2_enabled: false }),
      },
    })
    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    expect(await screen.findByText('MÜNCHEN')).toBeVisible()
    expect(screen.queryByText('München')).not.toBeInTheDocument()
  })

  it('reproduit la structure validée de la fiche entreprise derrière le flag', async () => {
    mockApi(routes(approvedProfile()))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    const drawer = await screen.findByRole('complementary', { name: 'H. Hüther GmbH' })
    expect(drawer).toHaveTextContent(
      'Construction de maisons individuelles · Belleville-en-Beaujolais (Rhône) · 5 salariés',
    )
    expect(drawer).toHaveTextContent('Mosbah Benzaoui')
    expect(drawer).toHaveTextContent('Président')
    expect(drawer).toHaveTextContent('publié sur le site')
    expect(drawer).toHaveTextContent('Source : registre national des entreprises')
    expect(drawer).toHaveTextContent('Source : site de l’entreprise')
    expect(drawer).toHaveTextContent('Source : analyse automatisée')
    expect(screen.getByRole('button', { name: 'Trouver le décideur' })).toBeEnabled()
    expect(drawer).toHaveTextContent('20 recherches restantes ce mois')
    const headings = Array.from(drawer.querySelectorAll('h3')).map((heading) => heading.textContent)
    expect(headings).toEqual([
      'Contact',
      'Identité',
      'Marchés publics',
      'Vous et cette entreprise',
    ])
    expect(drawer).toHaveTextContent('Aucun marché public attribué connu.')
    expect(drawer).toHaveTextContent("Aucune action pour l'instant.")
    expect(screen.queryByRole('heading', { name: 'Ses marchés' })).not.toBeInTheDocument()
  })

  it('floute le Contact en Découverte et présente Essentiel à 49 €', async () => {
    const directory = approvedProfile().directory!
    const publicDirectory = { ...directory }
    delete publicDirectory.director_display_name
    delete publicDirectory.director_display_title
    delete publicDirectory.phone
    delete publicDirectory.phone_source
    delete publicDirectory.phone_observed_at
    delete publicDirectory.published_email
    delete publicDirectory.published_email_source_url
    delete publicDirectory.published_email_observed_at
    delete publicDirectory.contact_observed_at
    mockApi(routes(approvedProfile({
      plan_code: 'discovery',
      directory: publicDirectory,
      contact_lookup: {
        state: 'locked',
        remaining: 0,
        monthly_quota: 0,
        source: 'apollo',
        removal_path: '/contact',
      },
    })))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    const contact = (await screen.findByRole('heading', { name: 'Contact' })).closest('section')
    expect(contact?.querySelector('[class*="companyContactBlur"]')).not.toBeNull()
    expect(contact).not.toHaveTextContent('Mosbah Benzaoui')
    expect(contact).not.toHaveTextContent('Camille Martin')
    expect(contact?.querySelectorAll('[class*="companyContactSkeleton"] > span')).toHaveLength(3)
    expect(contact).not.toHaveTextContent('contact@alya-batiment.example')
    expect(contact).toHaveTextContent(
      "Le contact du titulaire est inclus dans l'offre Essentiel — 49 €/mois",
    )
    expect(screen.getByRole('link', { name: "Voir l'offre Essentiel" })).toHaveAttribute(
      'href',
      '/tarifs',
    )
    expect(screen.queryByRole('button', { name: 'Trouver le décideur' })).not.toBeInTheDocument()
  })

  it('retire immédiatement les données Apollo après une révocation', async () => {
    const ready = approvedProfile({
      contact_lookup: {
        state: 'ready',
        remaining: 19,
        monthly_quota: 20,
        source: 'apollo',
        removal_path: '/contact',
        can_refresh: true,
        contacts: [{
          name: 'Alice Martin',
          title: 'Directrice commerciale',
          email: 'alice@holder.example',
          email_status: 'verified',
        }],
      },
    })
    mockApi({
      ...routes(ready),
      [`POST /companies/${COMPANY_PROFILE.company_key}/contact-lookup`]: {
        status: 409,
        body: { detail: { code: 'contact_lookup_suppressed' } },
      },
    })
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })
    const user = userEvent.setup()

    expect(await screen.findByText('alice@holder.example')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Actualiser' }))

    expect(await screen.findByText(/ne permet pas encore la recherche/)).toBeVisible()
    expect(screen.queryByText('Alice Martin')).not.toBeInTheDocument()
    expect(screen.queryByText('alice@holder.example')).not.toBeInTheDocument()
  })

  it('présente le premier marché seul sans cadence ni groupement', async () => {
    mockApi(routes(approvedProfile({ signals: [UNLOCKED_ITEM] })))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByText(/^Premier marché connu :/)).toBeVisible()
    expect(screen.queryByText(/marché par trimestre/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/groupement/i)).not.toBeInTheDocument()
  })

  it('résume deux marchés sur douze mois avant leur liste', async () => {
    const second = { ...UNLOCKED_ITEM, signal_id: 'sig_unlocked_2' }
    mockApi(routes(approvedProfile({
      signals: [UNLOCKED_ITEM, second],
      market_summary: {
        first_award_at: '2025-10-01',
        awards_per_quarter: '0.5',
        median_amounts: [{ value: '1000000', currency: 'EUR' }],
        consortium_share: '0',
        recurring_buyers: ['Commune de Villeneuve'],
        last_12_months: {
          awards_count: 2,
          total_amounts: [{ value: '2000000', currency: 'EUR' }],
          recurring_buyers: ['Commune de Villeneuve'],
        },
        resolution: 'company_key',
        source: 'public_awards',
      },
    })))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    const marketsHeading = await screen.findByRole('heading', { name: /^Marchés publics —/ })
    expect(marketsHeading).toHaveTextContent('2 gagnés en 12 mois')
    expect(marketsHeading).toHaveTextContent(/2\s000\s000\s€/)
    expect(marketsHeading).toHaveTextContent(
      'acheteurs récurrents : Commune de Villeneuve',
    )
    expect(screen.queryByText(/marché par trimestre/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/groupement/i)).not.toBeInTheDocument()
  })

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
        website_source: 'serper',
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
    expect(screen.getByText('Source du site : moteur de recherche')).toBeVisible()
    expect(screen.getByText('Source : registre')).toBeVisible()
    expect(screen.getByText('Alice Martin')).toBeVisible()
    expect(screen.getByText('Présidente')).toBeVisible()
    expect(screen.getByText('1,5 marché par trimestre')).toBeVisible()
    expect(screen.getByText('240 000 € de montant médian')).toBeVisible()
    const headings = screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent)
    expect(headings.indexOf('Identité')).toBeLessThan(headings.indexOf('Synthèse des marchés'))
    expect(headings.indexOf('Synthèse des marchés')).toBeLessThan(headings.indexOf('Ses marchés'))
  })

  it('cherche un décideur à la demande et affiche uniquement les données sourcées', async () => {
    const available: CompanyProfile = {
      ...COMPANY_PROFILE,
      contact_lookup: {
        state: 'available',
        remaining: 20,
        monthly_quota: 20,
        source: 'apollo',
        removal_path: '/contact',
      },
    }
    mockApi(routes(available))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })
    const user = userEvent.setup()

    expect(await screen.findByText('20 recherches restantes ce mois')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Trouver le décideur' }))

    expect(await screen.findByText('Alice Martin')).toBeVisible()
    expect(screen.getByText('Directrice commerciale')).toBeVisible()
    expect(screen.getByRole('link', { name: 'alice@holder.example' })).toHaveAttribute(
      'href',
      'mailto:alice@holder.example',
    )
    expect(screen.getByText('E-mail vérifié')).toBeVisible()
    expect(screen.getByText('84 salariés')).toBeVisible()
    expect(screen.getByText('+33 5 61 00 00 00')).toBeVisible()
    expect(screen.getAllByRole('link', { name: 'LinkedIn ↗' })).toHaveLength(2)
    expect(screen.getByText(/Recherche effectuée le 11 septembre 2026/)).toBeVisible()
    expect(screen.getByText('Source : Apollo')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Retrait' })).toHaveAttribute('href', '/contact')
    expect(screen.queryByText('—')).not.toBeInTheDocument()
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}/contact-lookup`, 'POST')).toHaveLength(1)
    const headings = screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent)
    expect(headings.indexOf('Contact')).toBeLessThan(headings.indexOf('Ses marchés'))
  })

  it('verrouille la recherche en Découverte avec une invitation vers les offres', async () => {
    const discovery: CompanyProfile = {
      ...COMPANY_PROFILE,
      contact_lookup: {
        state: 'locked',
        remaining: 0,
        monthly_quota: 0,
        source: 'apollo',
        removal_path: '/contact',
      },
    }
    mockApi(routes(discovery))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('button', { name: 'Trouver le décideur' })).toBeDisabled()
    expect(screen.getByText('0 recherche restante ce mois')).toBeVisible()
    expect(screen.getByRole('link', { name: 'Voir les offres' })).toHaveAttribute(
      'href',
      '/tarifs',
    )
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}/contact-lookup`, 'POST')).toHaveLength(0)
  })

  it('désactive la recherche quand le quota payant est épuisé et annonce sa reprise', async () => {
    const exhausted: CompanyProfile = {
      ...COMPANY_PROFILE,
      contact_lookup: {
        state: 'quota_exhausted',
        remaining: 0,
        monthly_quota: 20,
        next_reset_at: '2026-10-01T00:00:00Z',
        source: 'apollo',
        removal_path: '/contact',
      },
    }
    mockApi(routes(exhausted))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('button', { name: 'Trouver le décideur' })).toBeDisabled()
    expect(screen.getByText('Quota mensuel épuisé · reprise le 1 octobre 2026')).toBeVisible()
    expect(screen.queryByText('—')).not.toBeInTheDocument()
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}/contact-lookup`, 'POST')).toHaveLength(0)
  })

  it('désactive la recherche sans identité annuaire vérifiable', async () => {
    const unavailable: CompanyProfile = {
      ...COMPANY_PROFILE,
      contact_lookup: {
        state: 'identity_unavailable',
        remaining: 20,
        monthly_quota: 20,
        source: 'apollo',
        removal_path: '/contact',
      },
    }
    mockApi(routes(unavailable))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('button', { name: 'Trouver le décideur' })).toBeDisabled()
    expect(screen.getByText('Identité annuaire insuffisante pour lancer la recherche.')).toBeVisible()
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}/contact-lookup`, 'POST')).toHaveLength(0)
  })

  it('propose une actualisation seulement après quatre-vingt-dix jours', async () => {
    const stale: CompanyProfile = {
      ...COMPANY_PROFILE,
      contact_lookup: {
        state: 'ready',
        remaining: 19,
        monthly_quota: 20,
        source: 'apollo',
        removal_path: '/contact',
        researched_at: '2026-06-01T09:00:00Z',
        refresh_after: '2026-08-30T09:00:00Z',
        can_refresh: true,
        contacts: [{
          name: 'Alice Martin',
          title: 'Directrice commerciale',
          email: 'alice@holder.example',
          email_status: 'verified',
        }],
      },
    }
    mockApi(routes(stale))
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Actualiser' }))

    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}/contact-lookup`, 'POST')).toHaveLength(1)
  })

  it('conserve les contacts mais annonce la reprise après un quota épuisé lors du rafraîchissement', async () => {
    let reads = 0
    const stale: CompanyProfile = {
      ...COMPANY_PROFILE,
      contact_lookup: {
        state: 'ready',
        remaining: 1,
        monthly_quota: 20,
        source: 'apollo',
        removal_path: '/contact',
        researched_at: '2026-06-01T09:00:00Z',
        refresh_after: '2026-08-30T09:00:00Z',
        can_refresh: true,
        contacts: [{
          name: 'Alice Martin',
          title: 'Directrice commerciale',
          email: 'alice@holder.example',
          email_status: 'verified',
        }],
      },
    }
    const exhausted: CompanyProfile = {
      ...stale,
      contact_lookup: {
        ...stale.contact_lookup!,
        remaining: 0,
        can_refresh: false,
        next_reset_at: '2026-10-01T00:00:00Z',
      },
    }
    mockApi({
      ...routes(stale),
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: () => ({
        body: reads++ === 0 ? stale : exhausted,
      }),
      [`POST /companies/${COMPANY_PROFILE.company_key}/contact-lookup`]: {
        status: 403,
        body: { detail: { code: 'contact_lookup_quota_exhausted' } },
      },
    })
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Actualiser' }))

    expect(await screen.findByText('Alice Martin')).toBeVisible()
    expect(await screen.findByText('Quota mensuel épuisé · reprise le 1 octobre 2026')).toBeVisible()
    expect(screen.getByText('Le quota mensuel vient d’être épuisé.')).toBeVisible()
  })

  it('relit la fiche tant qu’une recherche concurrente est en cours', async () => {
    let reads = 0
    const researching: CompanyProfile = {
      ...COMPANY_PROFILE,
      contact_lookup: {
        state: 'researching',
        remaining: 19,
        monthly_quota: 20,
        source: 'apollo',
        removal_path: '/contact',
      },
    }
    const ready: CompanyProfile = {
      ...researching,
      contact_lookup: {
        ...researching.contact_lookup!,
        state: 'ready',
        contacts: [{
          name: 'Alice Martin',
          title: 'Directrice commerciale',
          email: 'alice@holder.example',
          email_status: 'verified',
        }],
      },
    }
    mockApi({
      ...routes(researching),
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: () => ({
        body: reads++ === 0 ? researching : ready,
      }),
    })
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('button', { name: 'Recherche en cours…' })).toBeDisabled()
    expect(await screen.findByText('Alice Martin', {}, { timeout: 3_000 })).toBeVisible()
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(2)
  })

  it('retire les données Contact si la relecture révoque le bloc', async () => {
    let reads = 0
    const researching: CompanyProfile = {
      ...COMPANY_PROFILE,
      contact_lookup: {
        state: 'researching',
        remaining: 19,
        monthly_quota: 20,
        source: 'apollo',
        removal_path: '/contact',
        organization: { employees: 84 },
        contacts: [{
          name: 'Alice Martin',
          title: 'Directrice commerciale',
          email: 'alice@holder.example',
          email_status: 'verified',
        }],
      },
    }
    const revoked: CompanyProfile = { ...COMPANY_PROFILE, contact_lookup: null }
    mockApi({
      ...routes(researching),
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: () => ({
        body: reads++ === 0 ? researching : revoked,
      }),
    })
    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByText('Alice Martin')).toBeVisible()
    await waitFor(() => expect(screen.queryByText('Alice Martin')).not.toBeInTheDocument(), {
      timeout: 3_000,
    })
    expect(screen.queryByRole('heading', { name: 'Contact' })).not.toBeInTheDocument()
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
