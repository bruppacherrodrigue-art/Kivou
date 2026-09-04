import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  ICP,
  PRO_STATUS,
  STALE_ITEM,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

describe('états indépendants des vues de référence', () => {

  it('conserve la liste utilisable quand le détail sélectionné échoue', async () => {
    mockApi({
      'GET /signals': { body: feedPage([STALE_ITEM]) },
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

    const table = await screen.findByRole('table')
    expect(within(table).getByText(STALE_ITEM.company.name!)).toBeVisible()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Le signal n’a pas pu être chargé.')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByRole('button', { name: /réessayer/i })).toBeVisible()
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

    expect(await screen.findByRole('heading', { level: 1, name: 'Alertes' })).toBeVisible()
    expect(await screen.findByRole('alert')).toHaveTextContent(/préférences/i)
    expect(screen.getByRole('button', { name: /réessayer/i })).toBeVisible()
  })

  it('conserve la liste pendant une nouvelle analyse locale du détail', async () => {
    const user = userEvent.setup()
    let detailReads = 0
    let rejectRetry!: (reason: unknown) => void
    mockApi({
      'GET /signals': { body: feedPage([STALE_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: () => {
        detailReads += 1
        if (detailReads === 1) return { status: 503, body: { detail: { code: 'signal_unavailable' } } }
        return new Promise((_resolve, reject) => { rejectRetry = reject })
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })

    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('Le signal n’a pas pu être chargé.')
    await user.click(screen.getByRole('button', { name: 'Réessayer' }))

    expect(await screen.findByRole('status', { name: 'Chargement du signal' })).toBeVisible()
    expect(screen.getByText(STALE_ITEM.company.name!)).toBeVisible()
    await act(async () => rejectRetry(new Error('detail retry failed')))
    expect(await screen.findByRole('alert')).toHaveTextContent('Le signal n’a pas pu être chargé.')
    expect(screen.getByText(STALE_ITEM.company.name!)).toBeVisible()
    expect(screen.getAllByRole('alert')).toHaveLength(1)
  })

  /* Sur la page Signaux, le feed (le tableau) et le détail (le tiroir) sont
   * deux ressources indépendantes : une panne du feed ne bloque ni n'annonce
   * deux fois la même chose. Ici le feed échoue mais le signal demandé par la
   * route profonde reste lisible directement — une seule alerte, dans le
   * tableau, et le tiroir affiche normalement son contenu. */
  it('n’annonce qu’une fois une panne initiale du feed sur une route profonde', async () => {
    mockApi({
      'GET /signals': {
        status: 503,
        body: { detail: { code: 'signal_unavailable' } },
      },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: PRO_STATUS },
    })

    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    expect(await screen.findByRole('heading', { level: 2, name: 'Voirie' })).toBeVisible()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Les informations n’ont pas pu être chargées.')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
  })


})
