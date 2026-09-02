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
  factualFallbackPresentation,
  feedPage,
  mockApi,
  recordedCalls,
  renderApp,
} from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const PUBLISHED_HEADLINE = 'Attribution documentée pour le lot communal de voirie'
const PUBLISHED_AWARD_SUMMARY = 'La source officielle documente l’attribution de ce lot communal.'

const PUBLISHED_UNLOCKED_ITEM = {
  ...UNLOCKED_ITEM,
  presentation: factualFallbackPresentation({
    artifactId: '1'.repeat(64),
    headline: PUBLISHED_HEADLINE,
    awardSummary: PUBLISHED_AWARD_SUMMARY,
    headlineEvidenceRefs: ['source:notice:26-104412:headline'],
    awardSummaryEvidenceRefs: ['source:notice:26-104412:award-summary'],
  }),
}

const PUBLISHED_UNLOCKED_DETAIL = {
  ...UNLOCKED_DETAIL,
  presentation: PUBLISHED_UNLOCKED_ITEM.presentation,
}

describe('vue d’ensemble de référence connectée aux données réelles', () => {
  it('ouvre la vue exacte à /app/dashboard sans réafficher l’ancien workspace', async () => {
    mockApi({
      'GET /signals': { body: feedPage([PUBLISHED_UNLOCKED_ITEM, LOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: PUBLISHED_UNLOCKED_DETAIL },
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
    expect(
      screen.getByText(PUBLISHED_UNLOCKED_ITEM.presentation.content.headline),
    ).toBeVisible()
    expect(screen.queryByText(UNLOCKED_ITEM.contract.title!)).toBeNull()
    expect(document.querySelector('.overview-focus-grid .priority-card')).not.toBeNull()
    expect(document.querySelector('.workspace-grid')).toBeNull()
    const priority = document.querySelector('.priority-card') as HTMLElement
    const facts = priority.querySelector('.priority-facts') as HTMLElement
    expect(within(facts).getByText('Montant total du marché')).toBeVisible()
    expect(within(facts).getByText('Date d’attribution')).toBeVisible()
    expect(within(facts).getByText('Acheteur')).toBeVisible()
    expect(within(facts).getByText('Lieu')).toBeVisible()
    for (const reason of UNLOCKED_ITEM.analysis.fit.reasons) {
      expect(within(priority).queryByText(reason)).toBeNull()
    }
    expect(within(priority).getByText('Un résumé factuel est publié, sans interprétation commerciale.')).toBeVisible()
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

    expect(document.querySelector('.signal-count')).toHaveTextContent('3 signaux')
    const paths = recordedCalls.map((call) => `${call.method} ${call.url}`)
    expect(paths.lastIndexOf('GET /billing/status')).toBeGreaterThan(paths.indexOf('GET /signals'))
  })
})
