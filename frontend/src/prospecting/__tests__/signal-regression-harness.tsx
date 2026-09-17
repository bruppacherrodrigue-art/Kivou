import type { ReactNode } from 'react'
import { Route, Routes, useLocation, useNavigationType } from 'react-router-dom'
import type { UnifiedStatus, UnlockedFeedItem } from '../../api/types'
import type { SessionState } from '../../auth/SessionProvider'
import { SignalsFeed } from '../../pages/SignalsFeed'
import { AUTHENTICATED, ICP, PRO_STATUS, UNLOCKED_DETAIL, UNLOCKED_ITEM, feedPage, renderApp } from '../../test/harness'
import { ProspectingProvider, useProspecting } from '../ProspectingProvider'

export const SIGNAL = { ...UNLOCKED_ITEM, status_revision: 4 }
export const DETAIL = { ...UNLOCKED_DETAIL, status_revision: 4, company_key: null }
export const BASE = {
  'GET /billing/status': { body: PRO_STATUS },
  'GET /target-icps': { body: [ICP] },
  'GET /target-icps/options': { body: { zones: [], sectors: [] } },
  'GET /signals': { body: feedPage([SIGNAL]) },
  [`GET /signals/${SIGNAL.signal_id}`]: { body: DETAIL },
  [`GET /signals/${SIGNAL.signal_id}/note`]: { body: { note: null, revision: 0, updated_at: null } },
}

export function item(patch: Partial<UnlockedFeedItem> = {}): UnlockedFeedItem {
  return { ...SIGNAL, ...patch }
}

export function workflow(status: UnifiedStatus, revision = 5) {
  return { signal_id: SIGNAL.signal_id, status, revision, updated_at: '2026-09-13T10:00:00Z', interaction: null }
}

function NavigationProbe() {
  const location = useLocation()
  const navigation = useNavigationType()
  const { scope } = useProspecting()
  return <><output data-testid="signal-location">{location.pathname}{location.search}</output><output data-testid="signal-navigation">{navigation}</output><output data-testid="scope-ready">{scope ? 'ready' : 'pending'}</output></>
}

export function renderSignal(ui: ReactNode, locale: 'fr' | 'en' = 'fr') {
  return renderApp(<ProspectingProvider><NavigationProbe />{ui}</ProspectingProvider>, { session: AUTHENTICATED, locale, route: '/app/signals?target_icp_id=icp_1' })
}

export function renderFeed(route = '/app/signals?target_icp_id=icp_1', session: SessionState = AUTHENTICATED) {
  return renderApp(<ProspectingProvider><NavigationProbe /><Routes>
    <Route path="/app/signals" element={<SignalsFeed />} />
    <Route path="/app/signals/:signalKey" element={<SignalsFeed />} />
  </Routes></ProspectingProvider>, { session, route })
}
