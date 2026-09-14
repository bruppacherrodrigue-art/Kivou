import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  DASHBOARD,
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
const ancillary = {
  'GET /dashboard': { body: DASHBOARD },
  'GET /target-icps/options': { body: { zones: [], sectors: [] } },
  [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: { body: { note: null, revision: 0, updated_at: null } },
}

describe('états indépendants des vues de référence', () => {

  it('conserve la liste utilisable quand le détail sélectionné échoue', async () => {
    mockApi({
      ...ancillary,
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

    const list = await screen.findByRole('region', { name: 'Liste des signaux' })
    expect(await within(list).findByText(STALE_ITEM.company.name!)).toBeVisible()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Ce signal ne peut pas être ouvert pour le moment.')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByRole('button', { name: /réessayer/i })).toBeVisible()
  })


  it('conserve le shell du compte quand les notifications échouent', async () => {
    mockApi({
      ...ancillary,
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
      ...ancillary,
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

    expect(await screen.findByRole('alert')).toHaveTextContent('Ce signal ne peut pas être ouvert pour le moment.')
    await user.click(screen.getByRole('button', { name: 'Réessayer' }))

    expect(await within(screen.getByRole('dialog')).findByRole('status')).toHaveTextContent('Chargement du signal')
    expect(screen.getByText(STALE_ITEM.company.name!)).toBeVisible()
    await act(async () => rejectRetry(new Error('detail retry failed')))
    expect(await screen.findByRole('alert')).toHaveTextContent('Ce signal ne peut pas être ouvert pour le moment.')
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
      ...ancillary,
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
    expect(alert).toHaveTextContent('Vos signaux ne sont pas chargés')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
  })


})
