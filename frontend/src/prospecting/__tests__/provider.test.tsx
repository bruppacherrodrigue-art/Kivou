import { StrictMode, type ReactNode } from 'react'
import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SessionProvider, useSession } from '../../auth/SessionProvider'
import { AUTHENTICATED, DISCOVERY_STATUS, ICP, ME, PRO_STATUS, mockApi } from '../../test/harness'
import { notifyTargetIcpChanged } from '../../targeting/targetIcpEvents'
import { ProspectingProvider, useProspecting, useProspectingResource } from '../ProspectingProvider'
import { usePersistedNote } from '../usePersistedNote'
import { saveConsultationPreference } from '../routeState'

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear() })

function Probe() {
  const p = useProspecting()
  const location = useLocation()
  const navigate = useNavigate()
  const session = useSession()
  const note = usePersistedNote(p.noteStore, { accountId: p.accountId, kind: 'signal', entityId: 's' })
  return <>
    <output data-testid="context">{JSON.stringify({ selection: p.selection, scope: p.scope, search: location.search, accessEpoch: p.accessEpoch, profiles: p.profiles.map((profile) => profile.target_icp_id), invalidParameters: p.invalidParameters })}</output>
    <output data-testid="query">{JSON.stringify(p.query)}</output>
    <output data-testid="profile-error">{p.profilesError ? 'failed' : 'none'}</output>
    <output data-testid="note">{note.status}</output>
    <output data-testid="draft">{note.draft}</output>
    <button onClick={() => p.setSelection({ minAmount: '90000', amountCurrency: 'EUR' })}>Threshold</button>
    <button onClick={p.resetSelection}>Reset</button>
    <button onClick={() => p.setSelection({ offerCategory: 'materials_and_components' })}>One offer</button>
    <button onClick={() => p.setSelection({ offerCategory: null })}>All offers</button>
    <button onClick={() => p.setSelection({ targetIcpId: 'icp_2' })}>Second profile</button>
    <button onClick={() => navigate('/app/companies')}>Companies</button>
    <button onClick={() => navigate(`${location.pathname}${location.search}&cursor=old-cursor&offset=100&q=beton&sort=recent&status=saved&presentation_artifact_id=${'a'.repeat(64)}`)}>Next page</button>
    <button onClick={() => note.setDraft('Brouillon privé')}>Edit</button>
    <button onClick={() => void session.signOut()}>Logout</button>
    <button onClick={() => session.adopt({ ...ME, account_id: 'acc_2' })}>Switch account</button>
    <button onClick={() => void p.refreshAccess()}>Access</button>
    <button onClick={p.acknowledgeInvalidParameters}>Acknowledge</button>
  </>
}
function ResourceProbe({ load, scopeIndependent = false, allowWithoutScope = false }: { load: (signal: AbortSignal) => Promise<string>; scopeIndependent?: boolean; allowWithoutScope?: boolean }) {
  const resource = useProspectingResource('review-resource', load, {}, true, { scopeIndependent, allowWithoutScope })
  return <><output data-testid="resource">{resource.error ? 'resource-error' : resource.data ?? 'resource-loading'}</output><button onClick={resource.reload}>Retry resource</button></>
}
function setup(extra = {}, strict = false, children: ReactNode = null) {
  const fetch = mockApi({
    'GET /target-icps': { body: [ICP] },
    'GET /target-icps/options': { body: { zones: [{ code: 'FR-31', label: 'Haute-Garonne', country: 'FR' }], sectors: [] } },
    'GET /billing/status': { body: PRO_STATUS },
    'GET /signals/s/note': { body: { note: null, revision: 0, updated_at: null } },
    'POST /auth/logout': { status: 204 },
    ...extra,
  })
  const content = <MemoryRouter initialEntries={['/app/signals?target_icp_id=icp_1&min_amount=70000&amount_currency=EUR&artifact=keep']}>
    <SessionProvider initialState={AUTHENTICATED}><ProspectingProvider><Probe />{children}</ProspectingProvider></SessionProvider>
  </MemoryRouter>
  const view = render(strict ? <StrictMode>{content}</StrictMode> : content)
  return { fetch, ...view }
}

describe('shared prospecting session', () => {
  // Existing harness defaults filter_level to basic for every plan; this is
  // the real backend Discovery entitlement (billing/catalogue.py).
  const discovery = { ...DISCOVERY_STATUS, entitlements: { ...DISCOVERY_STATUS.entitlements, filter_level: 'minimum' as const } }

  it('does not send paid consultation filters for a real Discovery account', async () => {
    const { fetch } = setup({ 'GET /billing/status': { body: discovery } })
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('"targetIcpId":"icp_1"'))
    expect(JSON.parse(screen.getByTestId('query').textContent!)).toEqual({ target_icp_id: 'icp_1' })
    act(() => screen.getByText('Threshold').click())
    act(() => screen.getByText('One offer').click())
    await waitFor(() => expect(JSON.parse(screen.getByTestId('query').textContent!)).toEqual({ target_icp_id: 'icp_1' }))
    expect(fetch.mock.calls.every(([, options]) => options?.method !== 'PATCH')).toBe(true)
  })

  it('removes revoked filters and over-limit profiles after a real downgrade', async () => {
    let status = PRO_STATUS
    setup({
      'GET /target-icps': { body: [ICP, { ...ICP, target_icp_id: 'icp_2' }] },
      'GET /billing/status': () => ({ body: status }),
    })
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('70000'))
    act(() => screen.getByText('Second profile').click())
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('"targetIcpId":"icp_2"'))
    status = { ...discovery, target_icps_over_limit: ['icp_2'] }
    act(() => screen.getByText('Access').click())
    await waitFor(() => expect(JSON.parse(screen.getByTestId('query').textContent!)).toEqual({ target_icp_id: 'icp_1' }))
    expect(JSON.parse(screen.getByTestId('context').textContent!).profiles).toEqual(['icp_1'])
    expect(JSON.parse(screen.getByTestId('context').textContent!).invalidParameters).toContain('target_icp_id')
  })

  it('keeps a removed-option warning after normalizing the URL', async () => {
    setup()
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('70000'))
    act(() => screen.getByText('One offer').click())
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('"offerCategory":"materials_and_components"'))
    // A fresh profile response removes a previously authorized offer.
    mockApi({
      'GET /target-icps': { body: [{ ...ICP, customer_input: { ...ICP.customer_input, offers: ['equipment_rental'], secondary_offers: [] } }] },
      'GET /target-icps/options': { body: { zones: [], sectors: [] } },
    })
    act(() => notifyTargetIcpChanged())
    await waitFor(() => expect(JSON.parse(screen.getByTestId('context').textContent!).selection?.offerCategory).toBeNull())
    await waitFor(() => expect(JSON.parse(screen.getByTestId('context').textContent!).search).not.toContain('offer_category'))
    expect(JSON.parse(screen.getByTestId('context').textContent!).invalidParameters).toContain('offer_category')
    act(() => screen.getByText('Acknowledge').click())
    expect(JSON.parse(screen.getByTestId('context').textContent!).invalidParameters).toEqual([])
  })

  it('does not expose the old selected scope after a profile refresh fails', async () => {
    let fail = false
    setup({ 'GET /target-icps': () => fail ? { status: 503 } : { body: [ICP] } })
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('70000'))
    fail = true
    act(() => notifyTargetIcpChanged())
    await waitFor(() => expect(screen.getByTestId('profile-error')).toHaveTextContent('failed'))
    expect(JSON.parse(screen.getByTestId('context').textContent!).scope).toBeNull()
  })

  it('blocks aggregate resource reads on initial profile failure and discards old data on refresh failure', async () => {
    let fail = true
    const load = vi.fn(async () => 'old-scoped-data')
    setup({ 'GET /target-icps': () => fail ? { status: 503 } : { body: [ICP] } }, false, <ResourceProbe load={load} />)
    await waitFor(() => expect(screen.getByTestId('resource')).toHaveTextContent('resource-error'))
    expect(load).not.toHaveBeenCalled()
    fail = false
    act(() => screen.getByText('Retry resource').click())
    await waitFor(() => expect(screen.getByTestId('resource')).toHaveTextContent('old-scoped-data'))
    fail = true
    act(() => notifyTargetIcpChanged())
    await waitFor(() => expect(screen.getByTestId('resource')).toHaveTextContent('resource-error'))
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('retries failed access discovery before reopening a blocked resource', async () => {
    let fail = true
    const load = vi.fn(async () => 'authorized-resource')
    setup({ 'GET /billing/status': () => fail ? { status: 503 } : { body: PRO_STATUS } }, false, <ResourceProbe load={load} />)
    await waitFor(() => expect(screen.getByTestId('resource')).toHaveTextContent('resource-error'))
    expect(load).not.toHaveBeenCalled()
    fail = false
    act(() => screen.getByText('Retry resource').click())
    await waitFor(() => expect(screen.getByTestId('resource')).toHaveTextContent('authorized-resource'))
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('keeps explicitly independent directory reads available when the targeting service fails', async () => {
    const load = vi.fn(async () => 'directory-result')
    setup({ 'GET /target-icps': { status: 503 } }, false, <ResourceProbe load={load} scopeIndependent />)
    await waitFor(() => expect(screen.getByTestId('resource')).toHaveTextContent('directory-result'))
    act(() => notifyTargetIcpChanged())
    await waitFor(() => expect(screen.getByTestId('profile-error')).toHaveTextContent('failed'))
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('lets known details show facts without a profile and reloads relevance when a target becomes available', async () => {
    let fail = true
    const load = vi.fn(async () => 'known-signal-facts')
    setup({ 'GET /target-icps': () => fail ? { status: 503 } : { body: [ICP] } }, false, <ResourceProbe load={load} allowWithoutScope />)
    await waitFor(() => expect(screen.getByTestId('resource')).toHaveTextContent('known-signal-facts'))
    await waitFor(() => expect(screen.getByTestId('profile-error')).toHaveTextContent('failed'))
    expect(load).toHaveBeenCalledTimes(1)
    fail = false
    act(() => notifyTargetIcpChanged())
    await waitFor(() => expect(JSON.parse(screen.getByTestId('context').textContent!).scope?.targetIcpId).toBe('icp_1'))
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2))
  })

  it('aborts a pre-downgrade resource and rejects its late protected result', async () => {
    let resolveOld!: (data: string) => void
    let reads = 0
    let status = PRO_STATUS
    let firstSignal!: AbortSignal
    const load = vi.fn((signal: AbortSignal) => ++reads === 1
      ? new Promise<string>((resolve) => { firstSignal = signal; resolveOld = resolve })
      : Promise.resolve('authorized-projection'))
    setup({ 'GET /billing/status': () => ({ body: status }) }, false, <ResourceProbe load={load} />)
    await waitFor(() => expect(reads).toBe(1))
    status = discovery
    act(() => screen.getByText('Access').click())
    await waitFor(() => expect(screen.getByTestId('resource')).toHaveTextContent('authorized-projection'))
    expect(firstSignal.aborted).toBe(true)
    await act(async () => resolveOld('old-premium-contact'))
    expect(screen.getByTestId('resource')).toHaveTextContent('authorized-projection')
    expect(screen.queryByText('old-premium-contact')).not.toBeInTheDocument()
  })

  it('restarts a profile read aborted by an access refresh and ignores its late response', async () => {
    let resolveOld!: (response: { body: unknown }) => void
    let reads = 0
    const { fetch } = setup({ 'GET /target-icps': () => ++reads === 1
      ? new Promise<{ body: unknown }>((resolve) => { resolveOld = resolve })
      : { body: [ICP] } })
    await waitFor(() => expect(reads).toBe(1))
    const first = fetch.mock.calls.find(([url]) => url === '/target-icps')!
    act(() => screen.getByText('Access').click())
    await waitFor(() => expect(JSON.parse(screen.getByTestId('context').textContent!).scope?.targetIcpId).toBe('icp_1'))
    expect(first[1]?.signal?.aborted).toBe(true)
    await act(async () => resolveOld({ body: [{ ...ICP, target_icp_id: 'late-profile' }] }))
    expect(JSON.parse(screen.getByTestId('context').textContent!).profiles).toEqual(['icp_1'])
  })

  it.each(['Threshold', 'Second profile', 'Reset'])('clears signed pagination when consultation changes through %s', async (action) => {
    setup({ 'GET /target-icps': { body: [ICP, { ...ICP, target_icp_id: 'icp_2' }] } })
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('70000'))
    act(() => screen.getByText('Next page').click())
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('old-cursor'))
    act(() => screen.getByText(action).click())
    await waitFor(() => expect(JSON.parse(screen.getByTestId('context').textContent!).search).not.toContain('cursor='))
    const params = new URLSearchParams(JSON.parse(screen.getByTestId('context').textContent!).search)
    expect(params.has('offset')).toBe(false)
    expect(params.get('q')).toBe('beton')
    expect(params.get('sort')).toBe('recent')
    expect(params.get('status')).toBe('saved')
    expect(params.get('presentation_artifact_id')).toBe('a'.repeat(64))
  })

  it('drops an old signed cursor when a refreshed matching revision changes its context', async () => {
    let revision = 1
    setup({ 'GET /target-icps': () => ({ body: [{ ...ICP, matching_revision: revision }] }) })
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('70000'))
    act(() => screen.getByText('Next page').click())
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('old-cursor'))
    revision = 2
    act(() => notifyTargetIcpChanged())
    await waitFor(() => expect(JSON.parse(screen.getByTestId('context').textContent!).scope?.targetRevision).toBe(2))
    await waitFor(() => expect(JSON.parse(screen.getByTestId('context').textContent!).search).not.toContain('cursor='))
  })

  it('validates URL scope and restores non-sensitive preferences across tabs without changing the profile', async () => {
    const { fetch } = setup()
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('70000'))
    act(() => screen.getByText('Threshold').click())
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('90000'))
    act(() => screen.getByText('Companies').click())
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('90000'))
    act(() => screen.getByText('Reset').click())
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('50000'))
    expect(fetch.mock.calls.every(([, options]) => options?.method !== 'PATCH')).toBe(true)
  })

  it('survives StrictMode effect replay and reloads matching revision events', async () => {
    let revision = 1
    setup({ 'GET /target-icps': () => ({ body: [{ ...ICP, matching_revision: revision }] }) }, true)
    await waitFor(() => expect(screen.getByTestId('note')).toHaveTextContent('idle'))
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('"targetRevision":1'))
    revision = 2
    act(() => notifyTargetIcpChanged())
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('"targetRevision":2'))
  })

  it('does not delete valid session preferences during StrictMode initialization', async () => {
    saveConsultationPreference('acc_1', { targetIcpId: 'icp_1', offerCategory: 'materials_and_components', subdivisionCode: null, minAmount: '70000', amountCurrency: 'EUR' })
    setup({}, true)
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('"offerCategory":"materials_and_components"'))
  })

  it('can explicitly remove an offer override instead of restoring the previous preference', async () => {
    setup()
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('70000'))
    act(() => screen.getByText('One offer').click())
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('"offerCategory":"materials_and_components"'))
    act(() => screen.getByText('All offers').click())
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('"offerCategory":null'))
  })

  it('purges private note memory, pending reads and session preferences on logout', async () => {
    const { fetch } = setup({ 'GET /signals/s/note': () => new Promise(() => {}) })
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('70000'))
    act(() => screen.getByText('Edit').click())
    const noteRequest = fetch.mock.calls.find(([url]) => url === '/signals/s/note')!
    expect(noteRequest[1]?.signal?.aborted).toBe(false)
    act(() => screen.getByText('Logout').click())
    await waitFor(() => expect(screen.queryByTestId('context')).not.toBeInTheDocument())
    expect(noteRequest[1]?.signal?.aborted).toBe(true)
    expect(sessionStorage.length).toBe(0)
  })

  it('purges immediately at logout intent even if the network logout remains pending', async () => {
    const { fetch } = setup({ 'GET /signals/s/note': () => new Promise(() => {}), 'POST /auth/logout': () => new Promise(() => {}) })
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('70000'))
    act(() => screen.getByText('Edit').click())
    const noteRequest = fetch.mock.calls.find(([url]) => url === '/signals/s/note')!
    act(() => screen.getByText('Logout').click())
    await waitFor(() => expect(screen.queryByTestId('context')).not.toBeInTheDocument())
    expect(noteRequest[1]?.signal?.aborted).toBe(true)
    expect(sessionStorage.length).toBe(0)
  })

  it('changes access epoch only through a server billing refresh', async () => {
    setup()
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('"accessEpoch":0'))
    act(() => screen.getByText('Access').click())
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('"accessEpoch":1'))
  })

  it('aborts the previous account note and ignores its late result after switching accounts', async () => {
    let resolveOld!: (value: { body: unknown }) => void
    let reads = 0
    const { fetch } = setup({ 'GET /signals/s/note': () => ++reads === 1
      ? new Promise<{ body: unknown }>((resolve) => { resolveOld = resolve })
      : { body: { note: 'Second account', revision: 2, updated_at: null } } })
    await waitFor(() => expect(screen.getByTestId('context')).toHaveTextContent('70000'))
    act(() => screen.getByText('Edit').click())
    const oldRequest = fetch.mock.calls.find(([url]) => url === '/signals/s/note')!
    act(() => screen.getByText('Switch account').click())
    await waitFor(() => expect(screen.getByTestId('draft')).toHaveTextContent('Second account'))
    expect(oldRequest[1]?.signal?.aborted).toBe(true)
    await act(async () => resolveOld({ body: { note: 'Secret of first account', revision: 1, updated_at: null } }))
    expect(screen.getByTestId('draft')).toHaveTextContent('Second account')
    expect(screen.queryByText('Secret of first account')).not.toBeInTheDocument()
  })

  it('never renders an old private response after a resource key changes', async () => {
    const resolvers: Array<(value: string) => void> = []
    function Resource() {
      const p = useProspecting()
      const result = useProspectingResource('detail', () => new Promise<string>((resolve) => resolvers.push(resolve)), { entity: 'a' })
      return <><output>{result.data ?? 'loading'}</output><button onClick={p.invalidate}>Invalidate</button></>
    }
    mockApi({ 'GET /target-icps': { body: [ICP] }, 'GET /target-icps/options': { body: { zones: [], sectors: [] } }, 'GET /billing/status': { body: PRO_STATUS } })
    render(<MemoryRouter><SessionProvider initialState={AUTHENTICATED}><ProspectingProvider><Resource /></ProspectingProvider></SessionProvider></MemoryRouter>)
    await waitFor(() => expect(resolvers.length).toBeGreaterThan(0))
    act(() => screen.getByText('Invalidate').click())
    await waitFor(() => expect(resolvers.length).toBeGreaterThan(1))
    await act(async () => resolvers[0]('private old content'))
    expect(screen.queryByText('private old content')).not.toBeInTheDocument()
    await act(async () => resolvers[resolvers.length - 1]('current content'))
    expect(screen.getByText('current content')).toBeInTheDocument()
  })
})
