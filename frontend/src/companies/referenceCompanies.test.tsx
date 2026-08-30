import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router-dom'
import { AppRoutes } from '../App'
import { useSession } from '../auth/SessionProvider'
import type { CompanyProfile, UnlockedDetail, UnlockedFeedItem } from '../api/types'
import {
  AUTHENTICATED,
  COMPANY_PROFILE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  ME,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  callsTo,
  feedPage,
  mockApi,
  recordedCalls,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const SECOND_ITEM: UnlockedFeedItem = {
  ...UNLOCKED_ITEM,
  signal_id: 'sig_company_second',
  company: { ...UNLOCKED_ITEM.company, name: 'Atelier Alpha SA' },
  contract: { ...UNLOCKED_ITEM.contract, title: 'Second marché documenté' },
}
const SECOND_DETAIL: UnlockedDetail = {
  ...UNLOCKED_DETAIL,
  ...SECOND_ITEM,
  company_key: 'cmp_company_second',
}
const SECOND_PROFILE: CompanyProfile = {
  ...COMPANY_PROFILE,
  company_key: SECOND_DETAIL.company_key!,
  official_identity: {
    ...COMPANY_PROFILE.official_identity,
    name: SECOND_ITEM.company.name!,
    address: '2 rue Alpha, 69000 Lyon',
  },
  related_signals: COMPANY_PROFILE.related_signals.map((signal) => ({
    ...signal,
    signal_id: SECOND_ITEM.signal_id,
    contract_title: SECOND_ITEM.contract.title,
  })),
}

const shellRoutes = {
  'GET /target-icps': { body: [ICP] },
  'GET /billing/status': { body: DISCOVERY_STATUS },
}

describe('workspace Entreprises exact et borné par les signaux accessibles', () => {
  it('résout les entreprises uniquement via les détails de signaux déverrouillés', async () => {
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    await screen.findByRole('heading', { level: 2, name: COMPANY_PROFILE.official_identity.name })
    expect(document.querySelector('.companies-workspace .companies-panel + .company-detail')).not.toBeNull()
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(1)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(1)
  })

  it('pagine tout le feed, déduplique et conserve l’ordre de découverte serveur', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': (request) => request.search.get('offset') === '20'
        ? {
            body: feedPage([UNLOCKED_ITEM, SECOND_ITEM], {
              page: { limit: 20, offset: 20, has_more: false, scan_truncated: false },
              freshness: 'all',
            }),
          }
        : {
            body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM], {
              page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
              freshness: 'all',
            }),
          },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    await screen.findByRole('heading', { level: 2, name: COMPANY_PROFILE.official_identity.name })
    const list = document.querySelector('.companies-list')
    expect(list).not.toBeNull()
    const rows = within(list as HTMLElement).getAllByRole('button')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent(COMPANY_PROFILE.official_identity.name)
    expect(rows[1]).toHaveTextContent(SECOND_PROFILE.official_identity.name)
    expect(callsTo('/signals', 'GET').map((call) => call.search.get('offset'))).toEqual(['0', '20'])
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(1)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('autorise une route profonde seulement après avoir découvert sa clé en page suivante', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': (request) => request.search.get('offset') === '20'
        ? {
            body: feedPage([SECOND_ITEM], {
              page: { limit: 20, offset: 20, has_more: false, scan_truncated: false },
              freshness: 'all',
            }),
          }
        : {
            body: feedPage([LOCKED_ITEM], {
              page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
              freshness: 'all',
            }),
          },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
      [`GET /companies/${SECOND_PROFILE.company_key}`]: { body: SECOND_PROFILE },
    })

    renderApp(<AppRoutes />, {
      route: `/app/companies/${SECOND_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { name: SECOND_PROFILE.official_identity.name })).toBeVisible()
    expect(callsTo('/signals', 'GET').map((call) => call.search.get('offset'))).toEqual(['0', '20'])
    const detailCall = callsTo(`/signals/${SECOND_ITEM.signal_id}`, 'GET')[0]
    const companyCall = callsTo(`/companies/${SECOND_PROFILE.company_key}`, 'GET')[0]
    expect(recordedCalls.indexOf(detailCall)).toBeLessThan(recordedCalls.indexOf(companyCall))
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('regroupe deux signaux distincts de la même entreprise sans doubler la fiche', async () => {
    const sameCompanyDetail: UnlockedDetail = {
      ...SECOND_DETAIL,
      company_key: COMPANY_PROFILE.company_key,
      company: UNLOCKED_DETAIL.company,
    }
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, SECOND_ITEM], { freshness: 'all' }) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: sameCompanyDetail },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    await screen.findByRole('heading', { name: COMPANY_PROFILE.official_identity.name })
    expect(document.querySelectorAll('.company-list-item')).toHaveLength(1)
    expect(screen.getByRole('button', { name: /Constructions Bertrand SA/ })).toHaveTextContent('2 marchés')
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(1)
  })

  it('refuse une route entreprise inconnue avant tout GET entreprise', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      'GET /companies/cmp_unknown_private': { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, {
      route: '/app/companies/cmp_unknown_private',
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { name: 'Fiche entreprise inaccessible' })).toBeVisible()
    expect(callsTo('/companies/cmp_unknown_private', 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(document.body.textContent).not.toContain(COMPANY_PROFILE.official_identity.address!)
  })

  it('ne demande une route profonde autorisée qu’après le détail déverrouillé qui fournit sa clé', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(
      await screen.findByRole('heading', { level: 2, name: COMPANY_PROFILE.official_identity.name }),
    ).toBeVisible()
    const detailCall = callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')[0]
    const companyCall = callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')[0]
    expect(detailCall).toBeDefined()
    expect(companyCall).toBeDefined()
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(detailCall && companyCall && recordedCalls.indexOf(detailCall)).toBeLessThan(
      companyCall ? recordedCalls.indexOf(companyCall) : -1,
    )
  })

  it('reste fail-closed si le détail révoque entre-temps l’accès annoncé par le feed', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: {
        body: {
          ...LOCKED_ITEM,
          signal_id: UNLOCKED_ITEM.signal_id,
          access: { granted: false, reason: 'plan_entitlement_required', upgrade_to: [] },
          read_at: '2026-08-29',
          language: 'fr',
        },
      },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { name: 'Fiche entreprise inaccessible' })).toBeVisible()
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('borne la concurrence des détails même si une page API contient beaucoup de signaux', async () => {
    let active = 0
    let peak = 0
    const items = Array.from({ length: 12 }, (_, index): UnlockedFeedItem => ({
      ...UNLOCKED_ITEM,
      signal_id: `sig_company_pool_${index}`,
      company: { ...UNLOCKED_ITEM.company, name: `Entreprise ${index}` },
    }))
    const routes: Parameters<typeof mockApi>[0] = {
      ...shellRoutes,
      'GET /signals': { body: feedPage(items, { freshness: 'all' }) },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    }
    for (const [index, item] of items.entries()) {
      routes[`GET /signals/${item.signal_id}`] = async () => {
        active += 1
        peak = Math.max(peak, active)
        await Promise.resolve()
        active -= 1
        return {
          body: {
            ...UNLOCKED_DETAIL,
            ...item,
            company_key: index === 0 ? COMPANY_PROFILE.company_key : `cmp_pool_${index}`,
          },
        }
      }
    }
    mockApi(routes)

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    await screen.findByRole('heading', { level: 2, name: COMPANY_PROFILE.official_identity.name })
    expect(peak).toBeLessThanOrEqual(4)
  })

  it('annonce une résolution tronquée sans présenter la liste comme exhaustive', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': {
        body: feedPage([UNLOCKED_ITEM], {
          page: { limit: 20, offset: 0, has_more: false, scan_truncated: true },
          freshness: 'all',
        }),
      },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    await screen.findByRole('heading', { level: 2, name: COMPANY_PROFILE.official_identity.name })
    expect(screen.getByRole('alert')).toHaveTextContent(/partielle|plafonnée/i)
    expect(screen.queryByRole('button', { name: 'Réessayer' })).not.toBeInTheDocument()
  })

  it('rend la résolution incomplète, jamais un faux vide, si aucune entreprise n’est résolue', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': {
        body: feedPage([], {
          page: { limit: 20, offset: 0, has_more: false, scan_truncated: true },
          freshness: 'all',
        }),
      },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { name: 'Résolution incomplète' })).toBeVisible()
    expect(document.body).not.toHaveTextContent('Aucune entreprise accessible')
    expect(callsTo('/companies', 'GET')).toHaveLength(0)
  })

  it('ignore le profil obsolète après une nouvelle sélection et conserve la navigation réelle', async () => {
    const user = userEvent.setup()
    let resolveFirst!: (value: { body: CompanyProfile }) => void
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, SECOND_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: () => new Promise((resolve) => {
        resolveFirst = resolve
      }),
      [`GET /companies/${SECOND_PROFILE.company_key}`]: { body: SECOND_PROFILE },
    })

    renderApp(<><AppRoutes /><LocationProbe /></>, { route: '/app/companies', session: AUTHENTICATED })

    const second = await screen.findByRole('button', { name: new RegExp(SECOND_PROFILE.official_identity.name) })
    await user.click(second)
    expect(
      await screen.findByRole('heading', { level: 2, name: SECOND_PROFILE.official_identity.name }),
    ).toBeVisible()
    expect(screen.getByTestId('location')).toHaveTextContent(`/app/companies/${SECOND_PROFILE.company_key}`)

    await act(async () => {
      resolveFirst({ body: COMPANY_PROFILE })
      await Promise.resolve()
    })
    expect(screen.getByRole('heading', { level: 2, name: SECOND_PROFILE.official_identity.name })).toBeVisible()
    expect(document.body.textContent).not.toContain(COMPANY_PROFILE.official_identity.address!)
  })

  it('ne peint ni erreur ni identité du profil A pendant le chargement du profil B', async () => {
    const user = userEvent.setup()
    let resolveSecond!: (value: { body: CompanyProfile }) => void
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, SECOND_ITEM], { freshness: 'all' }) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: {
        status: 503,
        body: { detail: { code: 'temporarily_unavailable' } },
      },
      [`GET /companies/${SECOND_PROFILE.company_key}`]: () => new Promise((resolve) => {
        resolveSecond = resolve
      }),
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })
    expect(await screen.findByRole('alert')).toHaveTextContent('La fiche entreprise n’a pas pu être chargée')

    await user.click(screen.getByRole('button', { name: new RegExp(SECOND_PROFILE.official_identity.name) }))
    expect(await screen.findByRole('status')).toHaveTextContent('Chargement')
    expect(screen.queryByText('La fiche entreprise n’a pas pu être chargée')).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain(COMPANY_PROFILE.official_identity.address!)

    await act(async () => {
      resolveSecond({ body: SECOND_PROFILE })
      await Promise.resolve()
    })
    expect(await screen.findByRole('heading', { name: SECOND_PROFILE.official_identity.name })).toBeVisible()
  })

  it('conserve le focus mobile sur le détail terminal, y compris en retapant la sélection active', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'innerWidth', 'get').mockReturnValue(640)
    let resolveSecond!: (value: { body: CompanyProfile }) => void
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, SECOND_ITEM], { freshness: 'all' }) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
      [`GET /companies/${SECOND_PROFILE.company_key}`]: () => new Promise((resolve) => {
        resolveSecond = resolve
      }),
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })
    const first = await screen.findByRole('button', { name: new RegExp(COMPANY_PROFILE.official_identity.name) })
    await screen.findByRole('heading', { name: COMPANY_PROFILE.official_identity.name })

    await user.click(first)
    await waitFor(() => expect(document.getElementById('company-detail')).toHaveFocus())

    await user.click(screen.getByRole('button', { name: new RegExp(SECOND_PROFILE.official_identity.name) }))
    await waitFor(() => expect(resolveSecond).toBeTypeOf('function'))
    expect(document.getElementById('company-detail')).not.toHaveFocus()
    await act(async () => {
      resolveSecond({ body: SECOND_PROFILE })
      await Promise.resolve()
    })
    await waitFor(() => expect(document.getElementById('company-detail')).toHaveFocus())
    expect(screen.getByRole('heading', { name: SECOND_PROFILE.official_identity.name })).toBeVisible()
  })

  it('rend une révocation 404 de la fiche comme inaccessible sans faux retry', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM], { freshness: 'all' }) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: {
        status: 404,
        body: { detail: { code: 'company_not_found' } },
      },
    })

    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('Fiche entreprise inaccessible')
    expect(screen.queryByRole('button', { name: 'Réessayer' })).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain(COMPANY_PROFILE.official_identity.address!)
  })

  it('annule les données privées tardives lorsque le compte connecté change', async () => {
    let feedCalls = 0
    let resolveAccountA!: (value: { body: ReturnType<typeof feedPage> }) => void
    mockApi({
      ...shellRoutes,
      'GET /signals': () => {
        feedCalls += 1
        if (feedCalls === 1) return new Promise((resolve) => { resolveAccountA = resolve })
        return { body: feedPage([SECOND_ITEM], { freshness: 'all' }) }
      },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
      [`GET /companies/${SECOND_PROFILE.company_key}`]: { body: SECOND_PROFILE },
    })

    renderApp(
      <><AppRoutes /><AdoptSecondAccount /></>,
      { route: '/app/companies', session: AUTHENTICATED },
    )
    fireEvent.click(screen.getByRole('button', { name: 'Basculer sur le compte B' }))
    expect(
      await screen.findByRole('heading', { level: 2, name: SECOND_PROFILE.official_identity.name }),
    ).toBeVisible()

    await act(async () => {
      resolveAccountA({ body: feedPage([UNLOCKED_ITEM], { freshness: 'all' }) })
      await Promise.resolve()
    })
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(0)
    expect(document.body.textContent).not.toContain(COMPANY_PROFILE.official_identity.address!)
  })

  it('arrête le pool de détails du compte précédent avant de lancer une tâche restante', async () => {
    const accountAItems = Array.from({ length: 5 }, (_, index): UnlockedFeedItem => ({
      ...UNLOCKED_ITEM,
      signal_id: `sig_account_a_${index}`,
      company: { ...UNLOCKED_ITEM.company, name: `Privée A ${index}` },
    }))
    const resolvers: Array<(value: { body: UnlockedDetail }) => void> = []
    let feedCalls = 0
    const routes: Parameters<typeof mockApi>[0] = {
      ...shellRoutes,
      'GET /signals': () => {
        feedCalls += 1
        return feedCalls === 1
          ? { body: feedPage(accountAItems, { freshness: 'all' }) }
          : { body: feedPage([SECOND_ITEM], { freshness: 'all' }) }
      },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
      [`GET /companies/${SECOND_PROFILE.company_key}`]: { body: SECOND_PROFILE },
    }
    for (const item of accountAItems.slice(0, 4)) {
      routes[`GET /signals/${item.signal_id}`] = () => new Promise((resolve) => resolvers.push(resolve))
    }
    routes[`GET /signals/${accountAItems[4].signal_id}`] = { body: UNLOCKED_DETAIL }
    mockApi(routes)

    renderApp(<><AppRoutes /><AdoptSecondAccount /></>, { route: '/app/companies', session: AUTHENTICATED })
    await waitFor(() => expect(resolvers).toHaveLength(4))
    fireEvent.click(screen.getByRole('button', { name: 'Basculer sur le compte B' }))
    expect(await screen.findByRole('heading', { name: SECOND_PROFILE.official_identity.name })).toBeVisible()

    await act(async () => {
      resolvers.forEach((resolve, index) => resolve({
        body: { ...UNLOCKED_DETAIL, ...accountAItems[index], company_key: `cmp_private_a_${index}` },
      }))
      await Promise.resolve()
    })
    expect(callsTo(`/signals/${accountAItems[4].signal_id}`, 'GET')).toHaveLength(0)
  })

  it('conserve les entreprises déjà autorisées quand une page suivante échoue et annonce le résultat partiel', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': (request) => request.search.get('offset') === '20'
        ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
        : {
            body: feedPage([UNLOCKED_ITEM], {
              page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
              freshness: 'all',
            }),
          },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    expect(
      await screen.findByRole('heading', { level: 2, name: COMPANY_PROFILE.official_identity.name }),
    ).toBeVisible()
    expect(screen.getByRole('alert')).toHaveTextContent('Liste partielle')
    expect(callsTo('/signals', 'GET').map((call) => call.search.get('offset'))).toEqual(['0', '20'])
  })

  it('garde le résultat autorisé si un détail échoue et permet une reprise locale honnête', async () => {
    const user = userEvent.setup()
    let secondAttempts = 0
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, SECOND_ITEM], { freshness: 'all' }) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${SECOND_ITEM.signal_id}`]: () => {
        secondAttempts += 1
        return secondAttempts === 1
          ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
          : { body: SECOND_DETAIL }
      },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    expect(
      await screen.findByRole('heading', { level: 2, name: COMPANY_PROFILE.official_identity.name }),
    ).toBeVisible()
    expect(screen.getByRole('alert')).toHaveTextContent('Liste partielle')
    await user.click(screen.getByRole('button', { name: 'Réessayer' }))
    await waitFor(() => expect(callsTo(`/signals/${SECOND_ITEM.signal_id}`, 'GET')).toHaveLength(2))
    expect(await screen.findByRole('button', { name: new RegExp(SECOND_PROFILE.official_identity.name) })).toBeVisible()
    expect(callsTo('/signals', 'GET')).toHaveLength(1)
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(1)
  })

  it('n’annonce qu’une seule fois la panne quand tous les détails échouent', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM], { freshness: 'all' }) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: {
        status: 503,
        body: { detail: { code: 'temporarily_unavailable' } },
      },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    await waitFor(() => expect(screen.getAllByRole('alert')).toHaveLength(1))
    expect(screen.getByRole('alert')).toHaveTextContent('Les entreprises n’ont pas pu être chargées')
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Les entreprises n’ont pas pu être vérifiées' })).toBeVisible()
  })

  it('réessaie uniquement le profil après une panne du GET entreprise autorisé', async () => {
    const user = userEvent.setup()
    let profileAttempts = 0
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM], { freshness: 'all' }) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: () => {
        profileAttempts += 1
        return profileAttempts === 1
          ? { status: 503, body: { detail: { code: 'temporarily_unavailable' } } }
          : { body: COMPANY_PROFILE }
      },
    })

    renderApp(<AppRoutes />, {
      route: `/app/companies/${COMPANY_PROFILE.company_key}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('La fiche entreprise n’a pas pu être chargée')
    await user.click(screen.getByRole('button', { name: 'Réessayer' }))
    expect(
      await screen.findByRole('heading', { level: 2, name: COMPANY_PROFILE.official_identity.name }),
    ).toBeVisible()
    expect(callsTo('/signals', 'GET')).toHaveLength(1)
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(1)
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(2)
  })

  it('redirige un 401 du feed vers la connexion sans aucune requête entreprise', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { status: 401, body: { detail: { code: 'not_authenticated' } } },
    })

    renderApp(<AppRoutes />, { route: '/app/companies', session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { name: 'Retrouver vos signaux' })).toBeVisible()
    expect(callsTo(`/companies/${COMPANY_PROFILE.company_key}`, 'GET')).toHaveLength(0)
  })

  it('conserve la composition, les libellés anglais et un seul main/h1', async () => {
    mockApi({
      ...shellRoutes,
      'GET /signals': { body: feedPage([UNLOCKED_ITEM], { freshness: 'all' }) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /companies/${COMPANY_PROFILE.company_key}`]: { body: COMPANY_PROFILE },
    })

    renderApp(<AppRoutes />, {
      route: '/app/companies',
      session: { status: 'authenticated', me: { ...ME, locale: 'en' } },
      locale: 'en',
    })

    expect(await screen.findByRole('heading', { name: COMPANY_PROFILE.official_identity.name })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Companies linked to signals' })).toBeVisible()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(document.querySelectorAll('main')).toHaveLength(1)
    expect(document.querySelector('.companies-workspace .companies-panel + .company-detail')).not.toBeNull()
  })
})

function AdoptSecondAccount() {
  const { adopt } = useSession()
  return (
    <button
      type="button"
      onClick={() => adopt({ ...ME, account_id: 'acc_2', account_display_name: 'Compte B' })}
    >
      Basculer sur le compte B
    </button>
  )
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}</output>
}
