import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import { notifyTargetIcpChanged } from '../targeting/targetIcpEvents'
import {
  AUTHENTICATED,
  ICP,
  LOCKED_ITEM,
  PRO_STATUS,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  UNLOCKED_PRESENTATION,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

describe('états indépendants des vues de référence', () => {
  it('conserve les signaux réels et annonce localement une panne de facturation', async () => {
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': {
        status: 503,
        body: { detail: { code: 'billing_unavailable' } },
      },
    })

    renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })

    expect(await screen.findByText(UNLOCKED_PRESENTATION.content.headline)).toBeVisible()
    const priority = document.querySelector('.priority-card') as HTMLElement
    expect(within(priority).getAllByRole('alert')).toHaveLength(1)
    expect(within(priority).getByRole('alert')).toHaveTextContent(/offre/i)
    expect(within(priority).getByRole('button', { name: /réessayer/i })).toBeVisible()
  })

  it('explique la panne de facturation même quand aucun signal n’est accessible', async () => {
    mockApi({
      'GET /signals': { body: feedPage([]) },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': {
        status: 503,
        body: { detail: { code: 'billing_unavailable' } },
      },
    })

    renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })

    const heading = await screen.findByRole('heading', {
      name: 'Aucun signal accessible pour le moment',
    })
    const priority = heading.closest('.priority-card') as HTMLElement
    expect(within(priority).getByRole('alert')).toHaveTextContent(/offre/i)
    expect(within(priority).getByRole('button', { name: /réessayer/i })).toBeVisible()
  })

  it('conserve la liste utilisable quand le détail sélectionné échoue', async () => {
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: {
        status: 503,
        body: { detail: { code: 'signal_unavailable' } },
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })

    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    const list = await screen.findByRole('heading', { name: 'Attributions documentées' })
    expect(within(list.closest('.feed-panel') as HTMLElement).getByText(UNLOCKED_ITEM.company.name!)).toBeVisible()
    expect(await screen.findByRole('alert')).toHaveTextContent(/signal/i)
    expect(screen.getByRole('button', { name: /réessayer/i })).toBeVisible()
  })

  it('conserve le détail quand la note privée échoue', async () => {
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        status: 503,
        body: { detail: { code: 'note_unavailable' } },
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })

    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { name: UNLOCKED_DETAIL.contract.title! })).toBeVisible()
    expect(await screen.findByRole('alert')).toHaveTextContent(/note.*chargée/i)
    expect(screen.getByRole('textbox', { name: 'Note sur ce signal' })).toBeDisabled()
  })

  it('conserve le contexte de facturation quand le feed échoue', async () => {
    mockApi({
      'GET /signals': {
        status: 503,
        body: { detail: { code: 'signal_unavailable' } },
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })

    renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })

    expect(await screen.findByText('Pro', { selector: '.demo-mode-badge' })).toBeVisible()
    expect(await screen.findByRole('alert')).toHaveTextContent(/informations.*chargées/i)
  })

  it('conserve le shell du compte quand les notifications échouent', async () => {
    mockApi({
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
      'GET /notification-preferences': {
        status: 503,
        body: { detail: { code: 'notification_unavailable' } },
      },
    })

    renderApp(<AppRoutes />, { route: '/app/notifications', session: AUTHENTICATED })

    expect(await screen.findByRole('heading', { level: 1, name: 'Notifications' })).toBeVisible()
    expect(await screen.findByRole('alert')).toHaveTextContent(/préférences/i)
    expect(screen.getByRole('button', { name: /réessayer/i })).toBeVisible()
  })

  it('marque explicitement la liste conservée pendant une nouvelle lecture', async () => {
    const user = userEvent.setup()
    let freshReads = 0
    let rejectRefresh!: (reason: unknown) => void
    mockApi({
      'GET /signals': (request) => {
        if (request.search.get('freshness') === 'all') {
          return { body: feedPage([]) }
        }
        freshReads += 1
        if (freshReads === 1) return { body: feedPage([UNLOCKED_ITEM]) }
        return new Promise((_resolve, reject) => { rejectRefresh = reject })
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })

    renderApp(<AppRoutes />, {
      route: '/app/signals/sig_absent',
      session: AUTHENTICATED,
    })

    await screen.findByRole('heading', { name: 'Signal non disponible dans cette lecture' })
    await user.click(screen.getByRole('button', { name: 'Réessayer' }))

    expect(await screen.findByText('Actualisation des données…')).toHaveAttribute('role', 'status')
    expect(screen.getByText(UNLOCKED_ITEM.company.name!)).toBeVisible()
    expect(within(document.querySelector('.workspace-grid') as HTMLElement).getAllByRole('status')).toHaveLength(1)
    await act(async () => rejectRefresh(new Error('refresh failed')))
    const feedPanel = screen.getByRole('heading', { name: 'Attributions documentées' })
      .closest('.feed-panel') as HTMLElement
    expect(await within(feedPanel).findByRole('alert')).toHaveTextContent(
      'L’actualisation a échoué. Les données affichées peuvent être anciennes.',
    )
    expect(within(feedPanel).getByText(UNLOCKED_ITEM.company.name!)).toBeVisible()
    expect(within(document.querySelector('.workspace-grid') as HTMLElement).getAllByRole('alert')).toHaveLength(1)
  })

  it('n’annonce qu’une fois une panne initiale du feed sur une route profonde', async () => {
    mockApi({
      'GET /signals': {
        status: 503,
        body: { detail: { code: 'signal_unavailable' } },
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })

    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    const workspace = document.querySelector('.workspace-grid') as HTMLElement
    await within(workspace).findByText('Les informations n’ont pas pu être chargées.')
    expect(within(workspace).getAllByRole('alert')).toHaveLength(1)
  })

  it('n’annonce qu’une fois une panne de pagination qui bloque une route profonde', async () => {
    mockApi({
      'GET /signals': (request) => request.search.get('offset') === '20'
        ? { status: 503, body: { detail: { code: 'feed_unavailable' } } }
        : {
            body: feedPage([UNLOCKED_ITEM], {
              page: { limit: 20, offset: 0, has_more: true, scan_truncated: false },
            }),
          },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })

    renderApp(<AppRoutes />, {
      route: '/app/signals/sig_absent_page_two',
      session: AUTHENTICATED,
    })

    const workspace = document.querySelector('.workspace-grid') as HTMLElement
    await within(workspace).findByText('Les informations n’ont pas pu être chargées.')
    expect(within(workspace).getAllByRole('alert')).toHaveLength(1)
    expect(within(workspace).getByText(UNLOCKED_ITEM.company.name!)).toBeVisible()
  })

  it('ne présente jamais un profil retenu comme actuel pendant ou après un refresh échoué', async () => {
    let reads = 0
    let rejectRefresh!: (reason: unknown) => void
    mockApi({
      'GET /target-icps': () => {
        reads += 1
        if (reads === 1) return { body: [ICP] }
        return new Promise((_resolve, reject) => { rejectRefresh = reject })
      },
      'GET /billing/status': { body: PRO_STATUS },
      'GET /me': { body: AUTHENTICATED.me },
    })

    renderApp(<AppRoutes />, { route: '/app/settings/profile', session: AUTHENTICATED })
    const profileLabel = `${ICP.label} · FR`
    expect(await screen.findByText(profileLabel)).toBeVisible()

    act(() => notifyTargetIcpChanged())
    expect(await screen.findByText('Chargement…', { selector: '.topbar-tools strong' })).toBeVisible()
    expect(screen.queryByText(profileLabel)).toBeNull()

    await act(async () => rejectRefresh(new Error('refresh failed')))
    expect(
      await screen.findByRole('button', { name: 'Réessayer le chargement du profil de ciblage' }),
    ).toBeVisible()
    expect(screen.queryByText(profileLabel)).toBeNull()
  })
})
