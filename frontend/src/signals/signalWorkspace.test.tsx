import { useLocation, useNavigate } from 'react-router-dom'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import type { CompanyProfile, UnlockedDetail, UnlockedFeedItem } from '../api/types'
import {
  AUTHENTICATED,
  CATALOGUE,
  COMPANY_PROFILE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  callsTo,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const SECOND_ITEM: UnlockedFeedItem = {
  ...UNLOCKED_ITEM,
  signal_id: 'sig_unlocked_2',
  company_key: 'cmp_second_opaque',
  company: { ...UNLOCKED_ITEM.company, name: 'Atelier Alpha SA' },
  factual_display: {
    ...UNLOCKED_ITEM.factual_display,
    headline: 'Atelier Alpha SA remporte « Deuxième marché public »',
    market_summary: 'Deuxième marché public',
    object_short: 'Deuxième marché public',
  },
  contract: {
    ...UNLOCKED_ITEM.contract,
    title: 'Deuxième marché public',
    buyer: { ...UNLOCKED_ITEM.contract.buyer!, name: 'Acheteur Deux' },
  },
}

const SECOND_DETAIL: UnlockedDetail = {
  ...UNLOCKED_DETAIL,
  ...SECOND_ITEM,
  company_key: SECOND_ITEM.company_key,
}

const SECOND_PROFILE: CompanyProfile = {
  ...COMPANY_PROFILE,
  company_key: SECOND_ITEM.company_key!,
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

const THIRD_ITEM: UnlockedFeedItem = {
  ...SECOND_ITEM,
  signal_id: 'sig_old_2022',
  company_key: 'cmp_old_opaque',
  company: { ...SECOND_ITEM.company, name: 'Entreprise Historique SA' },
  factual_display: {
    ...SECOND_ITEM.factual_display,
    headline: 'Entreprise Historique SA remporte « Marché ancien »',
    market_summary: 'Marché ancien',
    object_short: 'Marché ancien',
    date: { value: '2022-03-04', kind: 'award' },
  },
  event: { ...SECOND_ITEM.event, date: '2022-03-04', status: 'stale_award' },
}

function commonRoutes(items: UnlockedFeedItem[] = [UNLOCKED_ITEM, SECOND_ITEM]) {
  return {
    'GET /signals': { body: feedPage(items) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
    [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
      body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
    },
    [`GET /signals/${SECOND_ITEM.signal_id}/note`]: {
      body: { signal_id: SECOND_ITEM.signal_id, note: null, updated_at: null },
    },
    [`GET /companies/${UNLOCKED_ITEM.company_key}`]: { body: COMPANY_PROFILE },
    [`GET /companies/${SECOND_ITEM.company_key}`]: { body: SECOND_PROFILE },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
  }
}

function LocationProbe() {
  const { pathname, search, state } = useLocation()
  return (
    <>
      <output data-testid="location-path">{pathname}</output>
      <output data-testid="location-search">{search}</output>
      <output data-testid="location-state">{JSON.stringify(state)}</output>
    </>
  )
}

function HistoryControls() {
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => navigate(-1)}>Historique précédent</button>
      <button type="button" onClick={() => navigate(1)}>Historique suivant</button>
    </>
  )
}

function singlePaneMatchMedia() {
  return vi.fn((query: string): MediaQueryList => ({
    matches: query === '(max-width: 1179px)',
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
  }))
}

describe('navigation et historique du workspace Signaux', () => {
  it('porte la sélection dans la route, l’état et la carte active', async () => {
    const user = userEvent.setup()
    mockApi(commonRoutes())
    renderApp(<><AppRoutes /><LocationProbe /></>, {
      route: '/app/signals',
      session: AUTHENTICATED,
    })

    const second = await screen.findByRole('button', { name: /Atelier Alpha SA/ })
    await user.click(second)

    expect(screen.getByTestId('location-path')).toHaveTextContent('/app/signals/sig_unlocked_2')
    expect(screen.getByTestId('location-state')).toHaveTextContent('"kind":"feed"')
    expect(second).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByText('Acheteur Deux')).toBeVisible()
  })

  it('préserve le scroll de la liste et remonte seulement le panneau détail', async () => {
    const user = userEvent.setup()
    mockApi(commonRoutes())
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    await screen.findByRole('button', { name: /Atelier Alpha SA/ })
    const list = document.querySelector<HTMLElement>('.feed-panel')!
    const detail = document.querySelector<HTMLElement>('.detail-panel')!
    list.scrollTop = 360
    detail.scrollTop = 240

    await user.click(screen.getByRole('button', { name: /Atelier Alpha SA/ }))
    await screen.findByRole('heading', { level: 2, name: /Atelier Alpha SA remporte/ })

    expect(list.scrollTop).toBe(360)
    expect(detail.scrollTop).toBe(0)
    expect(document.querySelector('.detail-panel')).toBe(detail)
  })

  it('maintient la sélection et réserve la hauteur pendant un chargement lent', async () => {
    const user = userEvent.setup()
    let resolveSecond!: (value: { body: unknown }) => void
    mockApi({
      ...commonRoutes(),
      [`GET /signals/${SECOND_ITEM.signal_id}`]: () => new Promise((resolve) => { resolveSecond = resolve }),
    })
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    const second = await screen.findByRole('button', { name: /Atelier Alpha SA/ })
    await user.click(second)
    expect(second).toHaveAttribute('aria-pressed', 'true')
    const panel = document.querySelector('.detail-panel') as HTMLElement
    expect(await within(panel).findByRole('heading', { name: 'Chargement…' })).toBeVisible()
    expect(panel).not.toHaveTextContent('Commune de Villeneuve')

    await act(async () => resolveSecond({ body: SECOND_DETAIL }))
    expect(await within(panel).findByText('Acheteur Deux')).toBeVisible()
    expect(second).toHaveAttribute('aria-pressed', 'true')
  })

  it('ignore une ancienne réponse après plusieurs changements rapides', async () => {
    const user = userEvent.setup()
    let resolveFirst!: (value: { body: unknown }) => void
    let resolveSecond!: (value: { body: unknown }) => void
    mockApi({
      ...commonRoutes(),
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: () => new Promise((resolve) => { resolveFirst = resolve }),
      [`GET /signals/${SECOND_ITEM.signal_id}`]: () => new Promise((resolve) => { resolveSecond = resolve }),
    })
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    await waitFor(() => expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(1))
    await user.click(await screen.findByRole('button', { name: /Atelier Alpha SA/ }))
    await waitFor(() => expect(callsTo(`/signals/${SECOND_ITEM.signal_id}`, 'GET')).toHaveLength(1))
    await act(async () => resolveSecond({ body: SECOND_DETAIL }))
    expect(await screen.findByText('Acheteur Deux')).toBeVisible()
    await act(async () => resolveFirst({ body: UNLOCKED_DETAIL }))
    expect(screen.getByText('Acheteur Deux')).toBeVisible()
  })

  it('respecte précédent et suivant en restaurant le focus de la liste sur desktop', async () => {
    const user = userEvent.setup()
    mockApi(commonRoutes())
    renderApp(<><AppRoutes /><LocationProbe /><HistoryControls /></>, {
      route: '/app/signals',
      session: AUTHENTICATED,
    })

    const first = await screen.findByRole('button', { name: /Constructions Bertrand SA/ })
    const second = screen.getByRole('button', { name: /Atelier Alpha SA/ })
    await user.click(first)
    await user.click(second)
    await user.click(screen.getByRole('button', { name: 'Historique précédent' }))

    await waitFor(() => expect(screen.getByTestId('location-path')).toHaveTextContent('/app/signals/sig_unlocked_1'))
    await waitFor(() => expect(first).toHaveFocus())
    expect(first).toHaveAttribute('aria-pressed', 'true')

    await user.click(screen.getByRole('button', { name: 'Historique suivant' }))
    await waitFor(() => expect(second).toHaveFocus())
  })

  it('restaure un signal sélectionné au rechargement par deep-link', async () => {
    mockApi(commonRoutes())
    renderApp(<AppRoutes />, {
      route: `/app/signals/${SECOND_ITEM.signal_id}?view=history`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { level: 2, name: /Atelier Alpha SA remporte/ })).toBeVisible()
    expect(screen.getByRole('button', { name: /Atelier Alpha SA/ })).toHaveAttribute('aria-pressed', 'true')
    expect(callsTo(`/signals/${SECOND_ITEM.signal_id}`, 'GET')).toHaveLength(1)
  })

  it('focalise le détail en vue étroite puis rend le focus et le scroll à la liste', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('matchMedia', singlePaneMatchMedia())
    mockApi(commonRoutes())
    renderApp(<><AppRoutes /><LocationProbe /></>, {
      route: '/app/signals',
      session: AUTHENTICATED,
    })

    const row = await screen.findByRole('button', { name: /Atelier Alpha SA/ })
    const list = document.querySelector<HTMLElement>('.feed-panel')!
    list.scrollTop = 280
    await user.click(row)

    const title = await screen.findByRole('heading', { level: 2, name: /Atelier Alpha SA remporte/ })
    await waitFor(() => expect(title).toHaveFocus())
    expect(document.querySelector('.workspace-grid')).toHaveAttribute('data-pane', 'detail')
    expect(list.scrollTop).toBe(280)

    await user.click(screen.getByRole('button', { name: 'Retour à la liste' }))
    await waitFor(() => expect(screen.getByTestId('location-path')).toHaveTextContent('/app/signals'))
    await waitFor(() => expect(row).toHaveFocus())
    expect(list.scrollTop).toBe(280)
  })

  it('ne fait jamais défiler la fenêtre globale lors d’une sélection', async () => {
    const user = userEvent.setup()
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    })
    mockApi(commonRoutes())
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    await user.click(await screen.findByRole('button', { name: /Atelier Alpha SA/ }))
    await screen.findByRole('heading', { level: 2, name: /Atelier Alpha SA remporte/ })
    expect(scrollIntoView).not.toHaveBeenCalled()
  })

  it('ouvre l’historique avec une requête serveur dédiée', async () => {
    const user = userEvent.setup()
    mockApi({
      ...commonRoutes(),
      'GET /signals': (request) => ({
        body: request.search.get('view') === 'history'
          ? feedPage([THIRD_ITEM], {
              view: 'history',
              history_access: { scope: 'all_available', history_days: null },
              filter_access: { date_range: true, country: true, subdivision: true, status: true, sector: true },
            })
          : feedPage([UNLOCKED_ITEM]),
      }),
    })
    renderApp(<><AppRoutes /><LocationProbe /></>, {
      route: '/app/signals',
      session: AUTHENTICATED,
    })

    await user.click(await screen.findByRole('button', { name: 'Historique' }))
    expect(await screen.findByText('Entreprise Historique SA')).toBeVisible()
    expect(screen.getByTestId('location-search')).toHaveTextContent('view=history')
    expect(callsTo('/signals', 'GET').at(-1)?.search.get('freshness')).toBeNull()
    expect(callsTo('/signals', 'GET').at(-1)?.search.get('view')).toBe('history')
  })

  it('pagine l’historique par curseur opaque, déduplique et conserve l’ordre serveur', async () => {
    const user = userEvent.setup()
    const cursor = 'opaque.cursor.without.frontend.decoding'
    mockApi({
      ...commonRoutes(),
      'GET /signals': (request) => request.search.get('cursor') === cursor
        ? {
            body: feedPage([SECOND_ITEM, THIRD_ITEM], {
              view: 'history',
              page: { limit: 20, cursor, next_cursor: null, has_more: false, scan_truncated: false },
            }),
          }
        : {
            body: feedPage([UNLOCKED_ITEM, SECOND_ITEM], {
              view: 'history',
              page: { limit: 20, cursor: null, next_cursor: cursor, has_more: true, scan_truncated: false },
            }),
          },
    })
    renderApp(<AppRoutes />, {
      route: '/app/signals?view=history',
      session: AUTHENTICATED,
    })

    await user.click(await screen.findByRole('button', { name: 'Charger plus de signaux' }))
    await waitFor(() => expect(document.querySelectorAll('.signal-list .signal-item')).toHaveLength(3))
    expect(callsTo('/signals', 'GET').at(-1)?.search.get('cursor')).toBe(cursor)
    const names = [...document.querySelectorAll('.signal-list .signal-item strong')].map((node) => node.textContent)
    expect(names).toEqual(['Constructions Bertrand SA', 'Atelier Alpha SA', 'Entreprise Historique SA'])
  })

  it('conserve filtres, sélection et paramètres dans l’URL et la pagination', async () => {
    mockApi({
      ...commonRoutes(),
      'GET /signals': (request) => ({
        body: feedPage([UNLOCKED_ITEM, SECOND_ITEM], {
          view: 'history',
          history_access: { scope: 'all_available', history_days: null },
          filter_access: { date_range: true, country: true, subdivision: true, status: true, sector: true },
          page: { limit: 20, cursor: request.search.get('cursor'), next_cursor: null, has_more: false, scan_truncated: false },
        }),
      }),
    })
    renderApp(<><AppRoutes /><LocationProbe /></>, {
      route: `/app/signals/${SECOND_ITEM.signal_id}?view=history`,
      session: AUTHENTICATED,
    })

    await screen.findByRole('heading', { level: 2, name: /Atelier Alpha SA remporte/ })
    fireEvent.change(screen.getByLabelText('Du'), { target: { value: '2022-01-01' } })
    fireEvent.change(screen.getByLabelText('Au'), { target: { value: '2026-08-31' } })
    fireEvent.change(screen.getByLabelText('Pays (code ISO)'), { target: { value: 'fr' } })
    fireEvent.change(screen.getByLabelText('Zone'), { target: { value: 'fr-31' } })
    fireEvent.change(screen.getByLabelText('Statut temporel'), { target: { value: 'stale_award' } })
    fireEvent.change(screen.getByLabelText('Secteur (préfixe CPV)'), { target: { value: '4523x' } })

    await waitFor(() => {
      const call = callsTo('/signals', 'GET').at(-1)!
      expect(call.search.get('date_from')).toBe('2022-01-01')
      expect(call.search.get('date_to')).toBe('2026-08-31')
      expect(call.search.get('country')).toBe('FR')
      expect(call.search.get('subdivision_code')).toBe('FR-31')
      expect(call.search.get('status')).toBe('stale_award')
      expect(call.search.get('cpv_prefix')).toBe('4523')
    })
    expect(screen.getByTestId('location-path')).toHaveTextContent(`/app/signals/${SECOND_ITEM.signal_id}`)
    expect(screen.getByRole('button', { name: /Atelier Alpha SA/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it.each([
    ['grants_only', 0, 'Votre accès Découverte affiche uniquement vos signaux déjà débloqués.'],
    ['window', 30, 'Votre historique accessible couvre les 30 derniers jours.'],
    ['all_available', null, 'Tout l’historique disponible dans Kivou est accessible.'],
  ] as const)('explique honnêtement l’entitlement historique %s', async (scope, days, message) => {
    mockApi({
      ...commonRoutes(),
      'GET /signals': {
        body: feedPage([UNLOCKED_ITEM], {
          view: 'history',
          history_access: { scope, history_days: days },
          filter_access: {
            date_range: true,
            country: scope !== 'grants_only',
            subdivision: scope === 'all_available',
            status: scope === 'all_available',
            sector: scope !== 'grants_only',
          },
        }),
      },
    })
    renderApp(<AppRoutes />, { route: '/app/signals?view=history', session: AUTHENTICATED })

    expect(await screen.findByText(message)).toBeVisible()
    if (scope === 'grants_only') {
      expect(screen.getByLabelText('Pays (code ISO)')).toBeDisabled()
      expect(screen.getByText('Ce filtre n’est pas inclus dans votre accès actuel.')).toBeVisible()
    }
  })

  it('garde les faits et filtres lors d’une erreur de pagination récupérable', async () => {
    const user = userEvent.setup()
    const cursor = 'retry-cursor'
    let pageAttempts = 0
    mockApi({
      ...commonRoutes(),
      'GET /signals': (request) => {
        if (request.search.get('cursor') === cursor) {
          pageAttempts += 1
          return pageAttempts === 1
            ? { status: 503, body: { detail: { code: 'feed_unavailable' } } }
            : { body: feedPage([THIRD_ITEM], { view: 'history' }) }
        }
        return {
          body: feedPage([UNLOCKED_ITEM], {
            view: 'history',
            page: { limit: 20, cursor: null, next_cursor: cursor, has_more: true, scan_truncated: false },
          }),
        }
      },
    })
    renderApp(<AppRoutes />, { route: '/app/signals?view=history', session: AUTHENTICATED })

    const panel = document.querySelector('.feed-panel') as HTMLElement
    await user.click(await within(panel).findByRole('button', { name: 'Charger plus de signaux' }))
    const alert = await within(panel).findByRole('alert')
    expect(within(panel).getByText('Constructions Bertrand SA')).toBeVisible()
    await user.click(within(alert).getByRole('button', { name: 'Réessayer le chargement de la suite' }))
    expect(await within(panel).findByText('Entreprise Historique SA')).toBeVisible()
    expect(pageAttempts).toBe(2)
  })

  it('préserve la confidentialité et restaure le focus du teaser après Billing', async () => {
    const user = userEvent.setup()
    mockApi({
      ...commonRoutes([UNLOCKED_ITEM]),
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
      'GET /billing/plans': { body: CATALOGUE },
    })
    renderApp(<><AppRoutes /><HistoryControls /></>, {
      route: '/app/signals',
      session: AUTHENTICATED,
    })

    const locked = await screen.findByRole('button', { name: /Accès payant requis/ })
    expect(locked).not.toHaveTextContent('Constructions Bertrand')
    await user.click(locked)
    expect(await screen.findByRole('heading', { level: 1, name: 'Abonnement' })).toBeVisible()
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Historique précédent' }))
    const restored = await screen.findByRole('button', { name: /Accès payant requis/ })
    await waitFor(() => expect(restored).toHaveFocus())
  })
})
