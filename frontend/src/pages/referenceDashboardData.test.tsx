import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { within } from '@testing-library/react'
import { AppRoutes } from '../App'
import {
  AUTHENTICATED,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  feedPage,
  mockApi,
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
})
