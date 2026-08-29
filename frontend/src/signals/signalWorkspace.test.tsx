import { useLocation, useNavigate } from 'react-router-dom'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import type { FeedPage, UnlockedDetail, UnlockedFeedItem } from '../api/types'
import {
  AUTHENTICATED,
  CATALOGUE,
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

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const SECOND_ITEM: UnlockedFeedItem = {
  ...UNLOCKED_ITEM,
  signal_id: 'sig_unlocked_2',
  company: { ...UNLOCKED_ITEM.company, name: 'Deuxième SA' },
  contract: {
    ...UNLOCKED_ITEM.contract,
    title: 'Deuxième marché public',
    buyer: { ...UNLOCKED_ITEM.contract.buyer!, name: 'Acheteur Deux' },
  },
}

const SECOND_DETAIL: UnlockedDetail = {
  ...UNLOCKED_DETAIL,
  ...SECOND_ITEM,
  company_key: 'cmp_second_opaque',
}

const DEEP_ITEM: UnlockedFeedItem = {
  ...SECOND_ITEM,
  signal_id: 'sig_deep_page_2',
  company: { ...SECOND_ITEM.company, name: 'Deep Link SA' },
  contract: { ...SECOND_ITEM.contract, title: 'Marché trouvé en page deux' },
}

const DEEP_DETAIL: UnlockedDetail = {
  ...SECOND_DETAIL,
  ...DEEP_ITEM,
  company_key: 'cmp_deep_opaque',
}

function commonRoutes() {
  return {
    'GET /signals': { body: feedPage([UNLOCKED_ITEM, SECOND_ITEM]) },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
    [`GET /signals/${SECOND_ITEM.signal_id}`]: { body: SECOND_DETAIL },
    [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
      body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
    },
    [`GET /signals/${SECOND_ITEM.signal_id}/note`]: {
      body: { signal_id: SECOND_ITEM.signal_id, note: null, updated_at: null },
    },
    'GET /target-icps': { body: [ICP] },
    'GET /billing/status': { body: DISCOVERY_STATUS },
  }
}

function LocationProbe() {
  const { pathname, state } = useLocation()
  return (
    <>
      <output data-testid="location-path">{pathname}</output>
      <output data-testid="location-state">{JSON.stringify(state)}</output>
    </>
  )
}

function HistoryControls() {
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => navigate(-1)}>Précédent</button>
      <button type="button" onClick={() => navigate(1)}>Suivant</button>
    </>
  )
}

describe('workspace partagé des signaux', () => {
  it('porte la sélection réelle dans la route et dans l’état de navigation', async () => {
    const user = userEvent.setup()
    mockApi(commonRoutes())
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
      </>,
      { route: '/app/signals', session: AUTHENTICATED },
    )

    const second = await screen.findByRole('button', { name: /Deuxième SA/ })
    await user.click(second)

    expect(screen.getByTestId('location-path')).toHaveTextContent('/app/signals/sig_unlocked_2')
    expect(screen.getByTestId('location-state')).toHaveTextContent(
      '"signalSelection":{"kind":"feed","key":"sig_unlocked_2"',
    )
    expect(await screen.findByText('Acheteur Deux')).toBeVisible()
  })

  it('ignore une ancienne réponse détail et efface immédiatement le panneau précédent', async () => {
    const user = userEvent.setup()
    let resolveFirst!: (value: { body: unknown }) => void
    let resolveSecond!: (value: { body: unknown }) => void
    mockApi({
      ...commonRoutes(),
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: () =>
        new Promise((resolve) => { resolveFirst = resolve }),
      [`GET /signals/${SECOND_ITEM.signal_id}`]: () =>
        new Promise((resolve) => { resolveSecond = resolve }),
    })
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    await waitFor(() => expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(1))
    await user.click(await screen.findByRole('button', { name: /Deuxième SA/ }))
    await waitFor(() => expect(callsTo(`/signals/${SECOND_ITEM.signal_id}`, 'GET')).toHaveLength(1))
    const panel = document.querySelector('.detail-panel') as HTMLElement
    expect(panel).toHaveTextContent('Chargement…')
    expect(panel).not.toHaveTextContent('Commune de Villeneuve')

    await act(async () => resolveSecond({ body: SECOND_DETAIL }))
    expect(await within(panel).findByText('Acheteur Deux')).toBeVisible()
    await act(async () => resolveFirst({ body: UNLOCKED_DETAIL }))
    expect(within(panel).getByText('Acheteur Deux')).toBeVisible()
    expect(within(panel).queryByText('Commune de Villeneuve')).toBeNull()
  })

  it('restaure la sélection et le focus lors des retours et avances historiques', async () => {
    const user = userEvent.setup()
    mockApi(commonRoutes())
    renderApp(
      <>
        <AppRoutes />
        <LocationProbe />
        <HistoryControls />
      </>,
      { route: '/app/signals', session: AUTHENTICATED },
    )

    const first = await screen.findByRole('button', { name: /Constructions Bertrand SA/ })
    const second = screen.getByRole('button', { name: /Deuxième SA/ })
    await user.click(first)
    await user.click(second)
    expect(screen.getByTestId('location-path')).toHaveTextContent('/app/signals/sig_unlocked_2')

    await user.click(screen.getByRole('button', { name: 'Précédent' }))
    await waitFor(() => expect(screen.getByTestId('location-path')).toHaveTextContent('/app/signals/sig_unlocked_1'))
    await waitFor(() => expect(first).toHaveFocus())

    await user.click(screen.getByRole('button', { name: 'Précédent' }))
    await waitFor(() => expect(screen.getByTestId('location-path')).toHaveTextContent(/^\/app\/signals$/))
    await waitFor(() => expect(first).toHaveFocus())

    await user.click(screen.getByRole('button', { name: 'Suivant' }))
    await waitFor(() => expect(screen.getByTestId('location-path')).toHaveTextContent('/app/signals/sig_unlocked_1'))
    await waitFor(() => expect(first).toHaveFocus())
  })

  it('focalise et fait défiler le détail mobile puis restaure la ligne au retour', async () => {
    const user = userEvent.setup()
    const widthDescriptor = Object.getOwnPropertyDescriptor(window, 'innerWidth')
    const originalScroll = HTMLElement.prototype.scrollIntoView
    const scrollIntoView = vi.fn()
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 800 })
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    })
    try {
      mockApi(commonRoutes())
      renderApp(
        <>
          <AppRoutes />
          <HistoryControls />
        </>,
        { route: '/app/signals', session: AUTHENTICATED },
      )

      const second = await screen.findByRole('button', { name: /Deuxième SA/ })
      await user.click(second)
      const panel = document.querySelector('.detail-panel') as HTMLElement
      await waitFor(() => expect(panel).toHaveFocus())
      expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })

      await user.click(screen.getByRole('button', { name: 'Précédent' }))
      await waitFor(() => expect(second).toHaveFocus())
    } finally {
      if (widthDescriptor) Object.defineProperty(window, 'innerWidth', widthDescriptor)
      if (originalScroll) {
        Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
          configurable: true,
          value: originalScroll,
        })
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
      }
    }
  })

  it('résout un deep-link débloqué par pagination avant tout GET détail', async () => {
    let resolvePageTwo!: (value: { body: FeedPage }) => void
    mockApi({
      ...commonRoutes(),
      'GET /signals': (request) => {
        if (request.search.get('offset') === '20') {
          return new Promise((resolve) => { resolvePageTwo = resolve })
        }
        return {
          body: {
            ...feedPage([UNLOCKED_ITEM]),
            page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
          },
        }
      },
      [`GET /signals/${DEEP_ITEM.signal_id}`]: { body: DEEP_DETAIL },
      [`GET /signals/${DEEP_ITEM.signal_id}/note`]: {
        body: { signal_id: DEEP_ITEM.signal_id, note: null, updated_at: null },
      },
    })
    renderApp(<AppRoutes />, {
      route: `/app/signals/${DEEP_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    await waitFor(() => expect(callsTo('/signals', 'GET')).toHaveLength(2))
    expect(callsTo(`/signals/${DEEP_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    await act(async () => {
      resolvePageTwo({ body: feedPage([DEEP_ITEM], { offset: 20 }) as FeedPage })
    })

    expect(await screen.findByRole('heading', { level: 2, name: 'Marché trouvé en page deux' })).toBeVisible()
    expect(callsTo(`/signals/${DEEP_ITEM.signal_id}`, 'GET')).toHaveLength(1)
  })

  it('résout un deep-link verrouillé en page suivante sans détail ni note', async () => {
    mockApi({
      ...commonRoutes(),
      'GET /signals': (request) => request.search.get('offset') === '20'
        ? { body: feedPage([LOCKED_ITEM], { offset: 20 }) }
        : {
            body: {
              ...feedPage([UNLOCKED_ITEM]),
              page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
            },
          },
      'GET /billing/plans': { body: CATALOGUE },
    })
    renderApp(<AppRoutes />, {
      route: `/app/signals/${LOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { level: 1, name: 'Abonnement' })).toBeVisible()
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}/note`, 'GET')).toHaveLength(0)
  })

  it('confirme un deep-link historique via le feed all avant tout GET détail', async () => {
    const historical = {
      ...DEEP_ITEM,
      signal_id: 'sig_historical_unlocked',
      event: {
        ...DEEP_ITEM.event,
        status: 'stale_award' as const,
        type: null,
        date: '2025-02-01',
        headline: 'Deep Link SA a remporté un marché public en février 2025.',
        why_now: 'Ce signal historique reste accessible selon le serveur.',
        is_new_opportunity: false,
      },
    }
    const historicalDetail = { ...DEEP_DETAIL, ...historical }
    let resolveHistorical!: (value: { body: FeedPage }) => void
    mockApi({
      ...commonRoutes(),
      'GET /signals': (request) => request.search.get('freshness') === 'all'
        ? new Promise((resolve) => { resolveHistorical = resolve })
        : { body: feedPage([UNLOCKED_ITEM]) },
      [`GET /signals/${historical.signal_id}`]: { body: historicalDetail },
      [`GET /signals/${historical.signal_id}/note`]: {
        body: { signal_id: historical.signal_id, note: null, updated_at: null },
      },
    })
    renderApp(<AppRoutes />, {
      route: `/app/signals/${historical.signal_id}`,
      session: AUTHENTICATED,
    })

    await waitFor(() => {
      expect(callsTo('/signals', 'GET').some((call) => call.search.get('freshness') === 'all')).toBe(true)
    })
    expect(callsTo(`/signals/${historical.signal_id}`, 'GET')).toHaveLength(0)
    await act(async () => {
      resolveHistorical({ body: feedPage([historical], { freshness: 'all' }) as FeedPage })
    })

    expect(await screen.findByRole('heading', { level: 2, name: historical.contract.title! })).toBeVisible()
    expect(callsTo(`/signals/${historical.signal_id}`, 'GET')).toHaveLength(1)
    const list = document.querySelector('.signal-list') as HTMLElement
    expect(within(list).queryByText('Deep Link SA')).toBeNull()
  })

  it('ignore un lookup historique devenu obsolète après navigation vers un signal du feed', async () => {
    const user = userEvent.setup()
    const staleLookupItem = {
      ...DEEP_ITEM,
      signal_id: 'sig_lookup_stale',
      company: { ...DEEP_ITEM.company, name: 'Résultat historique obsolète SA' },
    }
    let resolveHistorical!: (value: { body: FeedPage }) => void
    mockApi({
      ...commonRoutes(),
      'GET /signals': (request) => request.search.get('freshness') === 'all'
        ? new Promise((resolve) => { resolveHistorical = resolve })
        : { body: feedPage([SECOND_ITEM]) },
    })
    renderApp(<AppRoutes />, {
      route: `/app/signals/${staleLookupItem.signal_id}`,
      session: AUTHENTICATED,
    })

    await waitFor(() => {
      expect(callsTo('/signals', 'GET').some((call) => call.search.get('freshness') === 'all')).toBe(true)
    })
    await user.click(screen.getByRole('button', { name: /Deuxième SA/ }))
    expect(await screen.findByText('Acheteur Deux')).toBeVisible()
    await act(async () => {
      resolveHistorical({ body: feedPage([staleLookupItem], { freshness: 'all' }) as FeedPage })
    })

    expect(document.querySelector('.signal-list')).not.toHaveTextContent('Résultat historique obsolète SA')
    expect(screen.getByText('Acheteur Deux')).toBeVisible()
    expect(callsTo(`/signals/${staleLookupItem.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('ne transforme pas un lookup all borné en faux signal introuvable', async () => {
    mockApi({
      ...commonRoutes(),
      'GET /signals': (request) => request.search.get('freshness') === 'all'
        ? {
            body: feedPage([], {
              freshness: 'all',
              page: { limit: 20, offset: 0, has_more: false, scan_truncated: true },
            }),
          }
        : { body: feedPage([UNLOCKED_ITEM]) },
    })
    renderApp(<AppRoutes />, {
      route: '/app/signals/sig_beyond_scan_cap',
      session: AUTHENTICATED,
    })

    expect(
      await screen.findByRole('heading', {
        level: 2,
        name: 'La lecture a été bornée : des signaux plus anciens existent au-delà de cette page.',
      }),
    ).toBeVisible()
    expect(screen.queryByText('Signal non disponible dans cette lecture')).toBeNull()
    expect(callsTo('/signals/sig_beyond_scan_cap', 'GET')).toHaveLength(0)
  })

  it('déclare indisponible un deep-link uniquement après épuisement des pages', async () => {
    const user = userEvent.setup()
    mockApi({
      ...commonRoutes(),
      'GET /signals': (request) => request.search.get('freshness') === 'all'
        ? { body: feedPage([], { freshness: 'all' }) }
        : request.search.get('offset') === '20'
          ? { body: feedPage([], { offset: 20 }) }
          : {
            body: {
              ...feedPage([UNLOCKED_ITEM]),
              page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
            },
          },
    })
    renderApp(<AppRoutes />, {
      route: '/app/signals/sig_absent',
      session: AUTHENTICATED,
    })

    expect(
      await screen.findByRole('heading', {
        level: 2,
        name: 'Signal non disponible dans cette lecture',
      }),
    ).toBeVisible()
    expect(callsTo('/signals', 'GET')).toHaveLength(3)
    expect(callsTo('/signals/sig_absent', 'GET')).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Réessayer' }))
    await waitFor(() => expect(callsTo('/signals', 'GET')).toHaveLength(6))
    expect(callsTo('/signals/sig_absent', 'GET')).toHaveLength(0)
  })

  it('conserve la confidentialité au clic d’un teaser et ne déduit aucun plan ouvrant', async () => {
    const user = userEvent.setup()
    mockApi({
      ...commonRoutes(),
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
    })
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    const locked = await screen.findByRole('button', { name: /accès payant requis/i })
    expect(locked).not.toHaveAccessibleName(expect.stringMatching(/Essentiel|Pro|Scale/))
    await act(async () => Promise.resolve())
    expect(callsTo('/billing/plans', 'GET')).toHaveLength(0)
    await user.click(locked)

    expect(await screen.findByRole('heading', { level: 1, name: 'Abonnement' })).toBeVisible()
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('restaure le focus du teaser verrouillé après retour depuis Billing', async () => {
    const user = userEvent.setup()
    mockApi({
      ...commonRoutes(),
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
      'GET /billing/plans': { body: CATALOGUE },
    })
    renderApp(
      <>
        <AppRoutes />
        <HistoryControls />
      </>,
      { route: '/app/signals', session: AUTHENTICATED },
    )

    const locked = await screen.findByRole('button', { name: /accès payant requis/i })
    await user.click(locked)
    expect(await screen.findByRole('heading', { level: 1, name: 'Abonnement' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Précédent' }))

    const restored = await screen.findByRole('button', { name: /accès payant requis/i })
    await waitFor(() => expect(restored).toHaveFocus())
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}/note`, 'GET')).toHaveLength(0)
  })

  it('rend honnêtement une panne du refresh après un deep-link épuisé', async () => {
    const user = userEvent.setup()
    let firstPageCalls = 0
    mockApi({
      ...commonRoutes(),
      'GET /signals': (request) => {
        if (request.search.get('freshness') === 'all') {
          return { body: feedPage([], { freshness: 'all' }) }
        }
        if (request.search.get('offset') === '20') return { body: feedPage([], { offset: 20 }) }
        firstPageCalls += 1
        return firstPageCalls === 1
          ? {
              body: {
                ...feedPage([UNLOCKED_ITEM]),
                page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
              },
            }
          : { status: 503, body: { detail: { code: 'feed_unavailable' } } }
      },
    })
    renderApp(<AppRoutes />, {
      route: '/app/signals/sig_absent_refresh_error',
      session: AUTHENTICATED,
    })

    await user.click(await screen.findByRole('button', { name: 'Réessayer' }))
    const list = document.querySelector('.signal-list') as HTMLElement
    await waitFor(() => expect(within(list).getByRole('alert')).toBeVisible())
    expect(within(list).getByRole('alert')).toHaveTextContent(
      'Les informations n’ont pas pu être chargées.',
    )
    expect(within(list).queryByText('Aucune attribution ne correspond à cette lecture.')).toBeNull()
  })

  it('laisse le listener HTTP invalider une session expirée sans rejouer de détail', async () => {
    mockApi({
      ...commonRoutes(),
      'GET /signals': { status: 401, body: { detail: { code: 'not_authenticated' } } },
    })
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Retrouver vos signaux' }),
    ).toBeVisible()
    expect(screen.getByRole('alert')).toHaveTextContent('Votre session a expiré')
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
  })

  it('préserve le paywall si le détail révoque un accès annoncé ouvert par le feed', async () => {
    mockApi({
      ...commonRoutes(),
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: {
        body: {
          ...LOCKED_ITEM,
          signal_id: UNLOCKED_ITEM.signal_id,
          access: { granted: false, reason: 'paid_plan_required', upgrade_to: [] },
          read_at: '2026-08-29T18:00:00+00:00',
          language: 'fr',
        },
      },
      'GET /billing/plans': { body: CATALOGUE },
    })
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { level: 1, name: 'Abonnement' })).toBeVisible()
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(1)
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}/note`, 'GET')).toHaveLength(0)
  })

  it('rend le compteur Discovery serveur relu après le feed d’activation', async () => {
    let billingCalls = 0
    let resolveFeed!: (value: { body: FeedPage }) => void
    const refreshedDiscovery = {
      ...DISCOVERY_STATUS,
      discovery: {
        ...DISCOVERY_STATUS.discovery,
        granted_signal_count: 3,
      },
    }
    mockApi({
      ...commonRoutes(),
      'GET /signals': () => new Promise((resolve) => { resolveFeed = resolve }),
      'GET /billing/status': () => {
        billingCalls += 1
        return { body: billingCalls === 1 ? DISCOVERY_STATUS : refreshedDiscovery }
      },
    })
    renderApp(<AppRoutes />, {
      route: { pathname: '/app/signals', state: { activationCompleted: true } },
      session: AUTHENTICATED,
    })

    await waitFor(() => expect(callsTo('/billing/status', 'GET')).toHaveLength(1))
    await act(async () => {
      resolveFeed({ body: feedPage([UNLOCKED_ITEM]) as FeedPage })
    })

    await waitFor(() => expect(callsTo('/billing/status', 'GET')).toHaveLength(2))
    expect(document.querySelector('.signal-count')).toHaveTextContent('3 · Découverte')
  })
})
