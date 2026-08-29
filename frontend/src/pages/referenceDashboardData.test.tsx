import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor, within } from '@testing-library/react'
import { AppRoutes } from '../App'
import type { FeedPage } from '../api/types'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  callsTo,
  feedPage,
  mockApi,
  recordedCalls,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

describe('vue d’ensemble de référence connectée aux données réelles', () => {
  it('ouvre la vue exacte à /app/dashboard sans réafficher l’ancien workspace', async () => {
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })

    renderApp(<AppRoutes />, { route: '/app/dashboard', session: AUTHENTICATED })

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Vue d’ensemble' }),
    ).toBeVisible()
    expect(
      screen.getByRole('heading', { level: 2, name: /attributions documentées/i }),
    ).toBeVisible()
    expect(screen.getByText(UNLOCKED_ITEM.contract.title!)).toBeVisible()
    expect(document.querySelector('.overview-focus-grid .priority-card')).not.toBeNull()
    expect(document.querySelector('.workspace-grid')).toBeNull()
    const priority = document.querySelector('.priority-card') as HTMLElement
    const facts = priority.querySelector('.priority-facts') as HTMLElement
    expect(within(facts).getByText('Attribution')).toBeVisible()
    expect(within(facts).getByText('Début prévu')).toBeVisible()
    expect(within(facts).getByText('Lieu')).toBeVisible()
    expect(within(facts).queryByText('Montant total du marché')).toBeNull()
    expect(within(facts).getByText('Non publié')).toBeVisible()
    for (const reason of UNLOCKED_ITEM.analysis.fit.reasons) {
      expect(within(priority).getByText(reason)).toBeVisible()
    }
    expect(within(priority).getByText(/Attribution publiée sur BOAMP/)).toBeVisible()
  })

  it('relit après le feed le compteur Discovery serveur, jamais le nombre de cartes', async () => {
    let billingCalls = 0
    let resolveFeed!: (value: { body: FeedPage }) => void
    const refreshed = {
      ...DISCOVERY_STATUS,
      discovery: { ...DISCOVERY_STATUS.discovery, granted_signal_count: 3 },
    }
    mockApi({
      'GET /signals': () => new Promise((resolve) => { resolveFeed = resolve }),
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': () => {
        billingCalls += 1
        return { body: billingCalls === 1 ? DISCOVERY_STATUS : refreshed }
      },
    })

    renderApp(<AppRoutes />, {
      route: { pathname: '/app/signals', state: { activationCompleted: true } },
      session: AUTHENTICATED,
    })

    await waitFor(() => expect(callsTo('/billing/status', 'GET')).toHaveLength(1))
    await act(async () => resolveFeed({ body: feedPage([UNLOCKED_ITEM]) as FeedPage }))
    await waitFor(() => expect(callsTo('/billing/status', 'GET')).toHaveLength(2))

    expect(document.querySelector('.signal-count')).toHaveTextContent('3 · Découverte')
    const paths = recordedCalls.map((call) => `${call.method} ${call.url}`)
    expect(paths.lastIndexOf('GET /billing/status')).toBeGreaterThan(paths.indexOf('GET /signals'))
  })
})
