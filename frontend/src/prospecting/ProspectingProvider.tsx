/* One account-owned lifetime for private drafts and scoped requests. Never a second session. */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError, onSignOutStarted } from '../api/client'
import { billing, companies, icps, signalNotes, type ConsultationQuery } from '../api/endpoints'
import type { BillingStatus, TargetIcp, TargetIcpOptions } from '../api/types'
import { useSession } from '../auth/SessionProvider'
import { subscribeToTargetIcpChanges } from '../targeting/targetIcpEvents'
import { prospectingKey, type ProspectingScope, type ResourceScopeOptions } from './queryKeys'
import { clearAccountConsultationPreferences, clearConsultationPreference, clearConsultationSearch, clearConsultationPagination, resolveConsultationState, saveConsultationPreference, writeConsultationSearch, type ConsultationPolicy, type ConsultationState } from './routeState'
import { createNoteStore, type NoteStore, type NoteTransport, type SavedNote } from './usePersistedNote'

type ResourceParameters = Parameters<typeof prospectingKey>[2]
interface ProspectingContextValue {
  accountId: string
  profiles: TargetIcp[]
  profile: TargetIcp | null
  profilesLoading: boolean
  profilesError: unknown | null
  policies: ConsultationPolicy[]
  targetOptions: TargetIcpOptions
  selection: ConsultationState | null
  invalidParameters: string[]
  acknowledgeInvalidParameters: () => void
  consultationCapabilities: { canChooseOffer: boolean; canChooseSubdivision: boolean; canChooseAmount: boolean }
  scope: ProspectingScope | null
  query: ConsultationQuery
  setSelection: (patch: Partial<ConsultationState>) => void
  resetSelection: () => void
  refreshProfiles: () => Promise<void>
  noteStore: NoteStore
  billingStatus: BillingStatus | null
  accessError: unknown | null
  accessLoading: boolean
  accessEpoch: number
  refreshAccess: () => Promise<void>
  invalidationEpoch: number
  invalidate: () => void
  resourceKey: (resource: string, parameters?: ResourceParameters, options?: ResourceScopeOptions) => string
  run: <T>(load: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal) => Promise<T>
}
const Context = createContext<ProspectingContextValue | null>(null)

/** The URL alias is deliberately not replaced with the public canonical key. */
export const apiNoteTransport: NoteTransport = {
  read: async (identity, options) => {
    if (identity.kind === 'signal') return signalNotes.read(identity.addressKey ?? identity.entityId, options)
    if (!identity.addressKey) throw new Error('Company notes require the addressed company key')
    const dossier = await companies.dossier(identity.addressKey, options)
    if (dossier.private_subject_key !== identity.entityId) throw new Error('Private company identity changed; reopen the dossier')
    return { note: dossier.note ?? null, revision: dossier.note_revision, updated_at: dossier.note_updated_at }
  },
  save: (identity, input, options) => {
    if (identity.kind === 'signal') return signalNotes.write(identity.addressKey ?? identity.entityId, input.note, input.expected_revision, options)
    if (!identity.addressKey) return Promise.reject(new Error('Company notes require the addressed company key'))
    return companies.note(identity.addressKey, input.note, input.expected_revision, options)
  },
  conflict: (error) => {
    if (!(error instanceof ApiError) || error.status !== 409) return null
    const { note, revision, updated_at } = error.extra
    return (note === null || typeof note === 'string') && typeof revision === 'number'
      && (updated_at === null || typeof updated_at === 'string')
      ? { note, revision, updated_at } as SavedNote : null
  },
}

interface Lifetime {
  noteStore: NoteStore
  run: ProspectingContextValue['run']
  abortRequests: () => void
  dispose: () => void
}
function lifetimeFor(accountId: string): Lifetime {
  const requests = new Set<AbortController>()
  const noteStore = createNoteStore(accountId, apiNoteTransport)
  let active = true
  const abortRequests = () => { for (const controller of requests) controller.abort(); requests.clear() }
  return {
    noteStore, abortRequests,
    run: async (load, signal) => {
      const controller = new AbortController()
      const abort = () => controller.abort()
      if (!active || signal?.aborted) controller.abort()
      signal?.addEventListener('abort', abort, { once: true })
      requests.add(controller)
      try {
        controller.signal.throwIfAborted()
        const result = await load(controller.signal)
        controller.signal.throwIfAborted()
        return result
      } finally { requests.delete(controller); signal?.removeEventListener('abort', abort) }
    },
    dispose: () => { active = false; abortRequests(); noteStore.dispose() },
  }
}

export function ProspectingProvider({ children }: { children: ReactNode }) {
  const { state } = useSession()
  const accountId = state.status === 'authenticated' ? state.me.account_id : null
  const [ending, setEnding] = useState(false)
  const previousAccount = useRef(accountId)
  useEffect(() => {
    if (previousAccount.current && previousAccount.current !== accountId) clearAccountConsultationPreferences(previousAccount.current)
    previousAccount.current = accountId
    setEnding(false)
  }, [accountId])
  useEffect(() => onSignOutStarted(() => {
    if (accountId) clearAccountConsultationPreferences(accountId)
    setEnding(true)
  }), [accountId])
  if (state.status !== 'authenticated' || ending) return null
  return <AccountProspectingProvider key={state.me.account_id} accountId={state.me.account_id}>{children}</AccountProspectingProvider>
}

function AccountProspectingProvider({ accountId, children }: { accountId: string; children: ReactNode }) {
  const [lifetime, setLifetime] = useState<Lifetime | null>(null)
  // Creating inside the effect prevents StrictMode's cleanup/replay from reusing a disposed store.
  useEffect(() => {
    const next = lifetimeFor(accountId)
    setLifetime(next)
    return () => next.dispose()
  }, [accountId])
  return lifetime ? <ReadyProspectingProvider accountId={accountId} lifetime={lifetime}>{children}</ReadyProspectingProvider> : null
}

function ReadyProspectingProvider({ accountId, lifetime, children }: { accountId: string; lifetime: Lifetime; children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [profiles, setProfiles] = useState<TargetIcp[]>([])
  const [options, setOptions] = useState<TargetIcpOptions>({ zones: [], sectors: [] })
  const [profilesLoading, setProfilesLoading] = useState(true)
  const [profilesError, setProfilesError] = useState<unknown>(null)
  const [billingStatus, setBillingStatus] = useState<BillingStatus | null>(null)
  const [accessError, setAccessError] = useState<unknown>(null)
  const [accessLoading, setAccessLoading] = useState(true)
  const [accessEpoch, setAccessEpoch] = useState(0)
  const [invalidationEpoch, setInvalidationEpoch] = useState(0)
  const [invalidParameters, setInvalidParameters] = useState<string[]>([])
  const acknowledgeInvalidParameters = useCallback(() => setInvalidParameters([]), [])
  const paginationScope = useRef<string | null>(null)
  const profileRequest = useRef(0)
  const accessRequest = useRef(0)
  const mounted = useRef(true)
  const invalidate = useCallback(() => setInvalidationEpoch((epoch) => epoch + 1), [])
  const refreshProfiles = useCallback(async () => {
    const requestId = ++profileRequest.current
    setProfilesLoading(true)
    setProfilesError(null)
    try {
      const [nextProfiles, nextOptions] = await lifetime.run((signal) => Promise.all([icps.list({ signal }), icps.options({ signal })]))
      if (!mounted.current || profileRequest.current !== requestId) return
      setProfiles(nextProfiles.filter((profile) => profile.status === 'active'))
      setOptions(nextOptions)
    } catch (error) {
      if (mounted.current && profileRequest.current === requestId && !(error instanceof DOMException && error.name === 'AbortError')) { setProfiles([]); setProfilesError(error) }
    } finally { if (mounted.current && profileRequest.current === requestId) setProfilesLoading(false) }
  }, [lifetime])
  const loadAccess = useCallback(async () => {
    const requestId = ++accessRequest.current
    setAccessLoading(true)
    try {
      const next = await lifetime.run((signal) => billing.status({ signal }))
      if (mounted.current && requestId === accessRequest.current) { setBillingStatus(next); setAccessError(null) }
    } catch (error) {
      if (mounted.current && requestId === accessRequest.current) setAccessError(error)
      throw error
    } finally { if (mounted.current && requestId === accessRequest.current) setAccessLoading(false) }
  }, [lifetime])
  const refreshAccess = useCallback(async () => {
    // Immediately discard premium requests/content, including when the refresh later fails.
    lifetime.abortRequests()
    setBillingStatus(null)
    setAccessEpoch((epoch) => epoch + 1)
    await Promise.all([loadAccess(), refreshProfiles()])
  }, [lifetime, loadAccess, refreshProfiles])
  useEffect(() => {
    mounted.current = true
    void refreshProfiles()
    void loadAccess().catch(() => {})
    const unsubscribe = subscribeToTargetIcpChanges(() => { void refreshProfiles() })
    return () => { mounted.current = false; profileRequest.current += 1; accessRequest.current += 1; unsubscribe() }
  }, [refreshProfiles, loadAccess, invalidate])

  const authorizedProfiles = useMemo(() => !billingStatus || profilesLoading || profilesError ? [] : profiles.filter(
    (profile) => !billingStatus.target_icps_over_limit.includes(profile.target_icp_id),
  ), [profiles, billingStatus, profilesLoading, profilesError])
  const canRefine = billingStatus?.entitlements.filter_level === 'basic' || billingStatus?.entitlements.filter_level === 'advanced'
  const consultationCapabilities = useMemo(() => ({ canChooseOffer: canRefine, canChooseSubdivision: canRefine, canChooseAmount: canRefine }), [canRefine])
  const policies = useMemo<ConsultationPolicy[]>(() => authorizedProfiles.map((profile) => {
    const input = profile.customer_input
    const threshold = input.minimum_contract_value
    return {
      targetIcpId: profile.target_icp_id,
      allowRefinement: canRefine,
      offers: canRefine ? [...new Set([...input.offers, ...input.secondary_offers])] : [],
      subdivisions: !canRefine ? [] : input.territory_subdivisions?.length ? input.territory_subdivisions
        : options.zones.filter((zone) => input.territories.includes(zone.country)).map((zone) => zone.code),
      currencies: canRefine ? ['EUR', 'CHF'] : [],
      defaultMinAmount: canRefine && threshold ? String(threshold.minimum_amount) : null,
      defaultAmountCurrency: canRefine ? threshold?.currency ?? null : null,
    }
  }), [authorizedProfiles, options, canRefine])
  const resolved = useMemo(() => resolveConsultationState(location.search, { accountId, policies }), [location.search, accountId, policies])
  const selection = resolved.selection
  const profile = authorizedProfiles.find((item) => item.target_icp_id === selection?.targetIcpId) ?? null
  const scope = useMemo<ProspectingScope | null>(() => selection && profile ? {
    accountId, targetIcpId: selection.targetIcpId, targetRevision: profile.matching_revision,
    offerCategory: selection.offerCategory, subdivisionCode: selection.subdivisionCode,
    minAmount: selection.minAmount, amountCurrency: selection.amountCurrency, accessEpoch,
  } : null, [accountId, selection, profile, accessEpoch])
  const query = useMemo<ConsultationQuery>(() => selection ? Object.fromEntries(Object.entries({
    target_icp_id: selection.targetIcpId, offer_category: selection.offerCategory, subdivision_code: selection.subdivisionCode,
    min_amount: selection.minAmount, amount_currency: selection.amountCurrency,
  }).filter(([, value]) => value !== null)) : {}, [selection])
  useEffect(() => {
    if (!selection) return
    if (resolved.invalidParameters.length) setInvalidParameters((current) => [...new Set([...current, ...resolved.invalidParameters])])
    saveConsultationPreference(accountId, selection)
    const nextScope = JSON.stringify(scope)
    const changedScope = paginationScope.current !== null && paginationScope.current !== nextScope
    paginationScope.current = nextScope
    const normalized = writeConsultationSearch(location.search, selection)
    const search = changedScope || resolved.invalidParameters.length ? clearConsultationPagination(normalized) : normalized
    if (search !== location.search) navigate({ pathname: location.pathname, search, hash: location.hash }, { replace: true, state: location.state })
  }, [selection, scope, resolved.invalidParameters, accountId, location, navigate])
  const setSelection = useCallback((patch: Partial<ConsultationState>) => {
    if (!selection) return
    let search = clearConsultationPagination(location.search)
    let base = selection
    if (patch.targetIcpId && patch.targetIcpId !== selection.targetIcpId) {
      const params = new URLSearchParams(clearConsultationSearch(search))
      params.set('target_icp_id', patch.targetIcpId)
      search = `?${params}`
      base = resolveConsultationState(search, { accountId, policies }).selection ?? selection
    }
    // A dialog may choose a different profile AND refinements in one submission.
    // Seed from the new profile's validated preferences, then retain every explicit field.
    search = writeConsultationSearch(search, { ...base, ...patch })
    // An explicitly cleared field must not resurrect its previous stored value.
    const validated = resolveConsultationState(search, { accountId, policies, storage: null }).selection
    if (validated) saveConsultationPreference(accountId, validated)
    navigate({ pathname: location.pathname, search, hash: location.hash }, { state: location.state })
  }, [selection, location, navigate, accountId, policies])
  const resetSelection = useCallback(() => {
    if (!selection) return
    clearConsultationPreference(accountId, selection.targetIcpId)
    navigate({ pathname: location.pathname, search: clearConsultationPagination(clearConsultationSearch(location.search)), hash: location.hash }, { state: location.state })
  }, [selection, accountId, location, navigate])
  const resourceKey = useCallback((resource: string, parameters?: ResourceParameters, options?: ResourceScopeOptions) => prospectingKey(resource, scope ?? {
    accountId, targetIcpId: '', targetRevision: 0, offerCategory: null, subdivisionCode: null, minAmount: null, amountCurrency: null, accessEpoch,
  }, { ...parameters, invalidationEpoch }, options), [scope, accountId, accessEpoch, invalidationEpoch])
  const value: ProspectingContextValue = { accountId, profiles: authorizedProfiles, profile, profilesLoading, profilesError, policies, targetOptions: options, selection, invalidParameters: [...new Set([...invalidParameters, ...resolved.invalidParameters])],
    acknowledgeInvalidParameters, consultationCapabilities,
    scope, query, setSelection, resetSelection, refreshProfiles, noteStore: lifetime.noteStore, billingStatus, accessError, accessLoading, accessEpoch, refreshAccess,
    invalidationEpoch, invalidate, resourceKey, run: lifetime.run }
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useProspecting() {
  const context = useContext(Context)
  if (!context) throw new Error('useProspecting requires an authenticated ProspectingProvider')
  return context
}

/** A stale key never returns its old data, even during the render before effect cleanup. */
export function useProspectingResource<T>(resource: string, load: (signal: AbortSignal) => Promise<T>, parameters?: ResourceParameters, enabled = true, options: ResourceScopeOptions = {}) {
  const { resourceKey, run, invalidate, profilesLoading, profilesError, refreshProfiles, scope, accessLoading, accessError, refreshAccess } = useProspecting()
  const requiresScope = !options.scopeIndependent && !options.allowWithoutScope
  const canLoad = enabled && (!requiresScope || (!profilesLoading && !profilesError && scope !== null)) && !accessLoading && !accessError
  const key = resourceKey(resource, parameters, options)
  const loader = useRef(load)
  useEffect(() => { loader.current = load }, [load])
  const [state, setState] = useState<{ key: string; data: T | null; loading: boolean; error: unknown | null }>({ key, data: null, loading: enabled, error: null })
  useEffect(() => {
    const controller = new AbortController()
    if (!canLoad) return () => controller.abort()
    setState({ key, data: null, loading: true, error: null })
    void run(loader.current, controller.signal).then(
      (data) => { if (!controller.signal.aborted) setState({ key, data, loading: false, error: null }) },
      (error) => { if (!controller.signal.aborted) setState({ key, data: null, loading: false, error }) },
    )
    return () => controller.abort()
  }, [key, run, canLoad])
  const reload = useCallback(() => {
    if (accessError) { void refreshAccess().catch(() => {}); return }
    if (requiresScope && profilesError) { void refreshProfiles(); return }
    invalidate()
  }, [accessError, refreshAccess, requiresScope, profilesError, refreshProfiles, invalidate])
  return { ...(state.key === key && canLoad ? state : { key, data: null, loading: enabled && ((requiresScope && profilesLoading) || accessLoading), error: accessError ?? (requiresScope ? profilesError : null) }), reload }
}
