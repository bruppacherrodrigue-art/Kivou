import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
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
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const FEED: FeedPage = {
  items: [UNLOCKED_ITEM, LOCKED_ITEM],
  total_returned: 2,
  page: { limit: 20, offset: 0, has_more: false, scan_truncated: false },
  excluded: { without_display_name: 0, by_freshness: 0 },
  read_at: '2026-08-18',
  freshness: 'new',
  language: 'fr',
  plan_code: 'discovery',
  policy: { feed: 'customer-feed-v0.1', recency: 'v1', paywall: 'kivou-paywall-v0.1' },
}

const ROUTES = {
  'GET /signals': { body: FEED },
  'GET /signals/sig_unlocked_1': { body: UNLOCKED_DETAIL },
  'GET /billing/status': { body: DISCOVERY_STATUS },
  'GET /target-icps': { body: [ICP] },
}

describe('workspace partagé des signaux', () => {
  it('sélectionne un signal débloqué dans le workspace master-detail', async () => {
    const user = userEvent.setup()
    mockApi(ROUTES)
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    const workspace = await screen.findByTestId('signal-workspace')
    const signalLink = await within(workspace).findByRole('link', {
      name: /Constructions Bertrand SA/,
    })
    expect(signalLink).toHaveAttribute('href', '/app/signals/sig_unlocked_1')

    await user.click(signalLink)

    expect(
      await within(workspace).findByRole('list', { name: 'Liste des signaux' }),
    ).toBeInTheDocument()
    expect(
      within(workspace).getByRole('link', { name: /Constructions Bertrand SA/ }),
    ).toHaveAttribute('aria-current', 'page')
    const detail = await within(workspace).findByRole('region', {
      name: 'Détail du signal sélectionné',
    })
    expect(within(detail).getByText('Commune de Villeneuve')).toBeInTheDocument()
  })

  it('sélectionne un signal verrouillé sans demander son détail protégé', async () => {
    const user = userEvent.setup()
    mockApi(ROUTES)
    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    const workspace = await screen.findByTestId('signal-workspace')
    await user.click(
      await within(workspace).findByRole('button', { name: /signal verrouillé/i }),
    )

    const detail = await within(workspace).findByRole('region', {
      name: 'Détail du signal sélectionné',
    })
    expect(within(detail).getByText(LOCKED_ITEM.headline)).toBeInTheDocument()
    expect(within(detail).getByRole('link', { name: 'Gérer mon accès' })).toHaveAttribute(
      'href',
      '/app/billing',
    )
    expect(callsTo('/signals/sig_locked_1', 'GET')).toHaveLength(0)
  })

  it('ouvre directement un signal débloqué dans le workspace partagé', async () => {
    mockApi(ROUTES)
    renderApp(<AppRoutes />, {
      route: '/app/signals/sig_unlocked_1',
      session: AUTHENTICATED,
    })

    const workspace = await screen.findByTestId('signal-workspace')
    expect(
      await within(workspace).findByRole('list', { name: 'Liste des signaux' }),
    ).toBeInTheDocument()
    expect(
      await within(workspace).findByRole('region', { name: 'Détail du signal sélectionné' }),
    ).toBeInTheDocument()
    const signalLink = within(workspace).getByRole('link', {
      name: /Constructions Bertrand SA/,
    })
    expect(signalLink).toHaveAttribute('href', '/app/signals/sig_unlocked_1')
    expect(signalLink).toHaveAttribute('aria-current', 'page')
    expect(callsTo('/signals/sig_unlocked_1', 'GET')).toHaveLength(1)
  })
})
