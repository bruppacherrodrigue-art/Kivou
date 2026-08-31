import {
  type RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { CheckCircle2 } from 'lucide-react'
import {
  Link,
  useLocation,
  useNavigate,
  useNavigationType,
  useParams,
} from 'react-router-dom'
import { MVP_TERRITORIES, territoryLabel } from '../api/capabilities'
import { companies, signals } from '../api/endpoints'
import { ApiError } from '../api/client'
import type {
  CompanyProfile as CompanyProfilePayload,
  UnlockedFeedItem,
} from '../api/types'
import { interpolate, plural, useI18n } from '../i18n'
import { publishedPresentation } from '../reference/dashboard/adapters'
import {
  type AuthorizedCompany,
  type AuthorizedCompanySignal,
  CompanyDetailMessage,
  CompanyProfileView,
  companyAwardHref,
  companyInitials,
} from './CompanyProfile'
import styles from './Companies.module.css'

const FEED_LIMIT = 20
const SINGLE_PANE_QUERY = '(max-width: 1179px)'

interface AccessSnapshot {
  status: 'loading' | 'ready' | 'error'
  companies: AuthorizedCompany[]
  unresolved: UnlockedFeedItem[]
  nextOffset: number | null
  scanTruncated: boolean
  error: unknown | null
  retrying: boolean
}

interface CompanySelectionNavigationState {
  companySelection: {
    kind: 'company-award'
    companyKey: string
    signalId: string
    fromList: boolean
  }
}

const INITIAL_ACCESS: AccessSnapshot = {
  status: 'loading',
  companies: [],
  unresolved: [],
  nextOffset: null,
  scanTruncated: false,
  error: null,
  retrying: false,
}

function companiesFrom(orderedItems: UnlockedFeedItem[]): AuthorizedCompany[] {
  const grouped = new Map<string, AuthorizedCompany>()
  for (const item of orderedItems) {
    if (!item.company_key || !item.company.name) continue
    const presentation = publishedPresentation(item.presentation)
    const signal: AuthorizedCompanySignal = {
      signalId: item.signal_id,
      presentationArtifactId: presentation?.artifact_id ?? null,
      summary: presentation?.content.award_summary ?? null,
      buyerName: item.contract.buyer?.name ?? null,
      location: item.contract.location,
      amountValue: item.contract.amount?.value ?? null,
      amountCurrency: item.contract.amount?.currency ?? null,
      awardDate: item.contract.dates.award,
      eventDate: item.event.date,
      eventClock: item.event.clock,
      fitReason: presentation?.content.fit_reason ?? null,
      recommendedAction: presentation?.content.recommended_action ?? null,
      sourceSystem: item.source.system,
      sourceNoticeId: item.source.notice_id,
      sourceUrl: item.source.url,
    }
    const existing = grouped.get(item.company_key)
    if (existing) {
      if (!existing.signals.some((candidate) => candidate.signalId === signal.signalId)) {
        existing.signals.push(signal)
      }
      continue
    }
    grouped.set(item.company_key, {
      key: item.company_key,
      name: item.company.name,
      country: item.company.country,
      signals: [signal],
    })
  }
  return [...grouped.values()]
}

function selectionState(
  companyKey: string,
  signalId: string,
  fromList: boolean,
): CompanySelectionNavigationState {
  return {
    companySelection: { kind: 'company-award', companyKey, signalId, fromList },
  }
}

function readSelectionState(value: unknown): CompanySelectionNavigationState['companySelection'] | null {
  if (typeof value !== 'object' || value === null || !('companySelection' in value)) return null
  const selection = (value as { companySelection?: unknown }).companySelection
  if (typeof selection !== 'object' || selection === null) return null
  const candidate = selection as Partial<CompanySelectionNavigationState['companySelection']>
  if (
    candidate.kind !== 'company-award'
    || typeof candidate.companyKey !== 'string'
    || candidate.companyKey.length === 0
    || typeof candidate.signalId !== 'string'
    || candidate.signalId.length === 0
    || typeof candidate.fromList !== 'boolean'
  ) return null
  return candidate as CompanySelectionNavigationState['companySelection']
}

function usesSinglePane(): boolean {
  if (typeof window.matchMedia === 'function') return window.matchMedia(SINGLE_PANE_QUERY).matches
  return window.innerWidth < 1180
}

export function Companies() {
  const { companyKey } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const navigationType = useNavigationType()
  const { t, locale, date, amount } = useI18n()
  const [access, setAccess] = useState<AccessSnapshot>(INITIAL_ACCESS)
  const accessRef = useRef(access)
  const orderedItemsRef = useRef<UnlockedFeedItem[]>([])
  const mounted = useRef(false)
  const accessGeneration = useRef(0)
  const [profile, setProfile] = useState<CompanyProfilePayload | null>(null)
  const [profileStatus, setProfileStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [profileError, setProfileError] = useState<unknown>(null)
  const [profileKey, setProfileKey] = useState<string | null>(null)
  const profileGeneration = useRef(0)
  const listPanelRef = useRef<HTMLElement | null>(null)
  const detailPanelRef = useRef<HTMLElement | null>(null)
  const rowRefs = useRef(new Map<string, HTMLAnchorElement>())
  const lastSelection = useRef<{ companyKey: string; signalId: string } | null>(null)
  const previousLocationKey = useRef(location.key)
  const pendingDetailFocus = useRef<string | null>(null)
  const [focusRequest, setFocusRequest] = useState(0)

  const requestedSignalId = useMemo(
    () => new URLSearchParams(location.search).get('signal'),
    [location.search],
  )

  const publishAccess = useCallback((next: AccessSnapshot) => {
    accessRef.current = next
    setAccess(next)
  }, [])

  const loadAccess = useCallback(async () => {
    const generation = ++accessGeneration.current
    const isCurrent = () => mounted.current && accessGeneration.current === generation
    publishAccess({ ...INITIAL_ACCESS })
    orderedItemsRef.current = []
    const seenSignals = new Set<string>()
    let offset = 0
    let nextOffset: number | null = null
    let scanTruncated = false
    let pageFailure: unknown | null = null
    let loadedPage = false

    while (true) {
      try {
        const page = await signals.feed({ freshness: 'all', limit: FEED_LIMIT, offset })
        if (!isCurrent()) return
        loadedPage = true
        for (const item of page.items) {
          if (item.locked || seenSignals.has(item.signal_id)) continue
          seenSignals.add(item.signal_id)
          orderedItemsRef.current.push(item)
        }
        scanTruncated ||= page.page.scan_truncated
        if (!page.page.has_more) break
        const candidate = page.page.offset + page.page.limit
        if (candidate <= offset) {
          scanTruncated = true
          break
        }
        offset = candidate
      } catch (caught) {
        if (!isCurrent()) return
        pageFailure = caught
        nextOffset = loadedPage ? offset : null
        break
      }
    }

    if (!loadedPage && pageFailure) {
      publishAccess({ ...INITIAL_ACCESS, status: 'error', error: pageFailure })
      return
    }

    const unresolved = orderedItemsRef.current.filter((item) => !item.company_key)
    const resolvedCompanies = companiesFrom(orderedItemsRef.current)
    if (resolvedCompanies.length === 0 && unresolved.length > 0 && !pageFailure && !scanTruncated) {
      publishAccess({
        status: 'error', companies: [], unresolved, nextOffset,
        scanTruncated, error: new Error('company_details_unavailable'), retrying: false,
      })
      return
    }
    publishAccess({
      status: 'ready',
      companies: resolvedCompanies,
      unresolved,
      nextOffset,
      scanTruncated,
      error: pageFailure,
      retrying: false,
    })
  }, [publishAccess])

  useEffect(() => {
    mounted.current = true
    void loadAccess()
    return () => {
      mounted.current = false
      accessGeneration.current += 1
      profileGeneration.current += 1
    }
  }, [loadAccess])

  const retryIncomplete = useCallback(async () => {
    const previous = accessRef.current
    if (previous.retrying) return
    if (previous.unresolved.length > 0) {
      await loadAccess()
      return
    }
    const generation = ++accessGeneration.current
    const isCurrent = () => mounted.current && accessGeneration.current === generation
    publishAccess({ ...previous, retrying: true })
    let nextOffset = previous.nextOffset
    let scanTruncated = previous.scanTruncated
    let pageFailure: unknown | null = null
    const seenSignals = new Set(orderedItemsRef.current.map((item) => item.signal_id))

    while (nextOffset !== null) {
      const requestedOffset = nextOffset
      try {
        const page = await signals.feed({ freshness: 'all', limit: FEED_LIMIT, offset: requestedOffset })
        if (!isCurrent()) return
        for (const item of page.items) {
          if (item.locked || seenSignals.has(item.signal_id)) continue
          seenSignals.add(item.signal_id)
          orderedItemsRef.current.push(item)
        }
        scanTruncated ||= page.page.scan_truncated
        if (!page.page.has_more) nextOffset = null
        else {
          const candidate = page.page.offset + page.page.limit
          if (candidate <= requestedOffset) {
            scanTruncated = true
            nextOffset = null
          } else nextOffset = candidate
        }
      } catch (caught) {
        if (!isCurrent()) return
        pageFailure = caught
        nextOffset = requestedOffset
        break
      }
    }

    const stillUnresolved = orderedItemsRef.current.filter((item) => !item.company_key)
    const resolvedCompanies = companiesFrom(orderedItemsRef.current)
    publishAccess({
      status: resolvedCompanies.length === 0 && stillUnresolved.length > 0 && !pageFailure && !scanTruncated
        ? 'error'
        : 'ready',
      companies: resolvedCompanies,
      unresolved: stillUnresolved,
      nextOffset,
      scanTruncated,
      error: pageFailure ?? (resolvedCompanies.length === 0 && stillUnresolved.length > 0
        ? new Error('company_details_unavailable')
        : null),
      retrying: false,
    })
  }, [loadAccess, publishAccess])

  const selectedCompany = useMemo(() => (
    companyKey
      ? access.companies.find((candidate) => candidate.key === companyKey) ?? null
      : null
  ), [access.companies, companyKey])
  const selectedSignal = useMemo(() => (
    selectedCompany && requestedSignalId
      ? selectedCompany.signals.find((candidate) => candidate.signalId === requestedSignalId) ?? null
      : null
  ), [requestedSignalId, selectedCompany])
  const selectedKey = selectedCompany && selectedSignal ? selectedCompany.key : null

  useEffect(() => {
    if (
      access.status !== 'ready'
      || !companyKey
      || !selectedCompany
      || requestedSignalId
      || selectedCompany.signals.length === 0
    ) return
    const signalId = selectedCompany.signals[0].signalId
    navigate(companyAwardHref(selectedCompany.key, signalId), {
      replace: true,
      state: selectionState(selectedCompany.key, signalId, false),
    })
  }, [access.status, companyKey, navigate, requestedSignalId, selectedCompany])

  const loadProfile = useCallback(async (key: string) => {
    const generation = ++profileGeneration.current
    setProfileKey(key)
    setProfile(null)
    setProfileError(null)
    setProfileStatus('loading')
    try {
      const result = await companies.get(key)
      if (!mounted.current || profileGeneration.current !== generation) return
      if (result.company_key !== key) {
        setProfileKey(key)
        setProfileStatus('error')
        return
      }
      setProfileKey(key)
      setProfile(result)
      setProfileStatus('ready')
    } catch (caught) {
      if (!mounted.current || profileGeneration.current !== generation) return
      setProfileError(caught)
      setProfileKey(key)
      setProfileStatus('error')
    }
  }, [])

  useEffect(() => {
    if (!selectedKey || access.status !== 'ready') {
      profileGeneration.current += 1
      setProfile(null)
      setProfileError(null)
      setProfileKey(null)
      setProfileStatus('idle')
      return
    }
    void loadProfile(selectedKey)
  }, [access.status, loadProfile, selectedKey])

  useLayoutEffect(() => {
    const detail = detailPanelRef.current
    if (detail && typeof detail.scrollTo === 'function') {
      detail.scrollTo({ top: 0, behavior: 'auto' })
    } else if (detail) detail.scrollTop = 0
  }, [companyKey, requestedSignalId])

  useEffect(() => {
    if (
      !pendingDetailFocus.current
      || pendingDetailFocus.current !== selectedSignal?.signalId
      || profileKey !== selectedCompany?.key
      || (profileStatus !== 'loading' && profileStatus !== 'ready' && profileStatus !== 'error')
    ) return
    const terminal = profileStatus === 'ready' || profileStatus === 'error'
    const frame = window.requestAnimationFrame(() => {
      detailPanelRef.current?.querySelector<HTMLElement>('#company-name')?.focus({ preventScroll: true })
      if (terminal) pendingDetailFocus.current = null
    })
    return () => window.cancelAnimationFrame(frame)
  }, [focusRequest, profileKey, profileStatus, selectedCompany?.key, selectedSignal?.signalId])

  useEffect(() => {
    if (previousLocationKey.current === location.key) return
    previousLocationKey.current = location.key
    if (
      companyKey
      && requestedSignalId
      && pendingDetailFocus.current === requestedSignalId
    ) return
    if (navigationType === 'PUSH' && companyKey) return

    const navigationSelection = readSelectionState(location.state)
    const focusSelection = companyKey && requestedSignalId
      ? {
          companyKey: selectedCompany?.key ?? navigationSelection?.companyKey ?? companyKey,
          signalId: selectedSignal?.signalId ?? navigationSelection?.signalId ?? requestedSignalId,
        }
      : lastSelection.current ?? (navigationSelection
        ? { companyKey: navigationSelection.companyKey, signalId: navigationSelection.signalId }
        : null)
    if (!focusSelection) return
    lastSelection.current = focusSelection

    if (companyKey && requestedSignalId && usesSinglePane()) {
      pendingDetailFocus.current = requestedSignalId
      setFocusRequest((current) => current + 1)
      return
    }
    const frame = window.requestAnimationFrame(() => rowRefs.current.get(focusSelection.signalId)?.focus())
    return () => window.cancelAnimationFrame(frame)
  }, [
    companyKey,
    location.key,
    location.state,
    navigationType,
    requestedSignalId,
    selectedCompany?.key,
    selectedSignal?.signalId,
  ])

  const requestDetailFocus = (signalId: string) => {
    pendingDetailFocus.current = signalId
    setFocusRequest((current) => current + 1)
  }

  const backToList = () => {
    if (selectedCompany && selectedSignal) {
      lastSelection.current = { companyKey: selectedCompany.key, signalId: selectedSignal.signalId }
    }
    const origin = readSelectionState(location.state)
    if (origin?.fromList) navigate(-1)
    else navigate('/app/companies', { replace: true, state: null })
  }

  const partial = access.status === 'ready' && (
    access.unresolved.length > 0 || access.nextOffset !== null || access.scanTruncated || access.error !== null
  )
  const retryablePartial = access.nextOffset !== null || access.unresolved.length > 0
  const detailOwnsAccessAlert = Boolean(companyKey && (
    access.status === 'error'
    || (partial && (!selectedCompany || !requestedSignalId || !selectedSignal))
  ))
  const copy = t.reference.companiesPage
  const awardCards = access.companies.flatMap((company) => (
    company.signals.map((signal) => ({ company, signal }))
  ))

  const displayTerritory = (company: AuthorizedCompany, signal: AuthorizedCompanySignal) => {
    if (signal.location) {
      const value = [signal.location.locality, signal.location.postal_code, signal.location.country]
        .filter(Boolean)
        .join(', ')
      if (value) return value
    }
    const knownTerritory = MVP_TERRITORIES.find((candidate) => candidate.code === company.country)
    if (knownTerritory) return territoryLabel(knownTerritory, locale)
    return company.country ?? copy.territoryMissing
  }

  return (
    <div
      className={`companies-workspace ${styles.workspace}`}
      data-pane={companyKey ? 'detail' : 'list'}
    >
      <aside
        ref={listPanelRef}
        className={`companies-panel ${styles.listPanel}`}
        data-master-detail-pane="list"
        aria-labelledby="companies-list-title"
      >
        <div className="panel-heading">
          <div>
            <p className="section-label">{copy.publishedHolders}</p>
            <h2 id="companies-list-title">{copy.listTitle}</h2>
          </div>
          <span className="signal-count">{access.status === 'loading' ? '…' : awardCards.length}</span>
        </div>
        <p className="companies-panel-note">{copy.listBoundary} {t.companiesIndex.partial}</p>

        {access.status === 'error' ? (
          <div role={detailOwnsAccessAlert ? undefined : 'alert'} className="companies-panel-note">
            <strong>{t.companiesIndex.errorTitle}</strong>
            <button type="button" onClick={() => void loadAccess()}>{t.reference.retry}</button>
          </div>
        ) : null}
        {partial ? (
          <div role={detailOwnsAccessAlert ? undefined : 'alert'} className="companies-panel-note">
            <strong>{t.companiesIndex.partialResultTitle}</strong>
            <span> {access.scanTruncated ? copy.truncatedResolution : t.companiesIndex.partialResultBody}</span>
            {access.nextOffset !== null || access.unresolved.length > 0 ? (
              <button
                type="button"
                disabled={access.retrying}
                onClick={() => void retryIncomplete()}
              >
                {access.retrying ? t.reference.loading : t.reference.retry}
              </button>
            ) : null}
          </div>
        ) : null}

        <div className="companies-list" aria-busy={access.status === 'loading'}>
          {access.status === 'ready' && access.companies.length === 0 && !partial
            ? <p className="companies-panel-note">{t.companiesIndex.emptyTitle}</p>
            : null}
          {awardCards.map(({ company, signal }) => {
            const selected = company.key === selectedCompany?.key
              && signal.signalId === selectedSignal?.signalId
            const publishedAmount = amount(signal.amountValue, signal.amountCurrency)
              ?? t.reference.missingValue
            const eventDate = date(signal.eventDate)
            const awardDate = eventDate ?? date(signal.awardDate)
            const publishedDate = signal.eventClock === 'notification'
              ? eventDate
                ? interpolate(copy.notifiedOn, { date: eventDate })
                : copy.notificationDateMissing
              : signal.eventClock === 'publication'
                ? eventDate
                  ? interpolate(copy.publishedOn, { date: eventDate })
                  : copy.publicationDateMissing
                : awardDate
                  ? interpolate(copy.awardedOn, { date: awardDate })
                  : copy.awardDateMissing
            const count = company.signals.length
            const href = companyAwardHref(company.key, signal.signalId)
            return (
              <Link
                ref={(node) => {
                  if (node) rowRefs.current.set(signal.signalId, node)
                  else rowRefs.current.delete(signal.signalId)
                }}
                to={href}
                replace={selected}
                state={selectionState(company.key, signal.signalId, true)}
                className={`company-list-item ${styles.companyLink}${selected ? ' is-selected' : ''}`}
                aria-current={selected ? 'true' : undefined}
                onClick={(event) => {
                  lastSelection.current = { companyKey: company.key, signalId: signal.signalId }
                  if (usesSinglePane() || event.detail === 0) requestDetailFocus(signal.signalId)
                }}
                key={signal.signalId}
              >
                <span className="company-list-avatar" aria-hidden="true">{companyInitials(company.name)}</span>
                <span className="company-list-content">
                  <span className="company-list-heading">
                    <strong>{company.name}</strong>
                  </span>
                  <span className={styles.companyRole}>{copy.winningCompany}</span>
                  {selected ? (
                    <span className={styles.selectedState}>
                      <CheckCircle2 aria-hidden="true" /> {copy.selected}
                    </span>
                  ) : null}
                  <span className={styles.awardLabel}>{copy.recentAward}</span>
                  <span className={`company-list-event ${styles.summary}`}>
                    {signal.summary ?? copy.objectMissing}
                  </span>
                  <span className={styles.buyer}>
                    {signal.buyerName
                      ? interpolate(copy.buyer, { buyer: signal.buyerName })
                      : copy.buyerMissing}
                  </span>
                  <span className={`company-list-meta ${styles.cardMeta}`}>
                    <span>{publishedAmount}</span>
                    <span>{publishedDate}</span>
                    <span>{displayTerritory(company, signal)}</span>
                  </span>
                  <span className={styles.awardCount}>
                    {interpolate(plural(count, copy.contractOne, copy.contractOther), { count })}
                  </span>
                </span>
              </Link>
            )
          })}
        </div>
      </aside>

      {renderDetail({
        access,
        companyKey,
        requestedSignalId,
        selectedCompany,
        selectedSignal,
        profile,
        profileKey,
        profileStatus,
        profileError,
        retryProfile: selectedKey && selectedSignal ? () => {
          requestDetailFocus(selectedSignal.signalId)
          void loadProfile(selectedKey)
        } : undefined,
        retryAccess: () => void loadAccess(),
        retryIncomplete: partial && retryablePartial ? () => void retryIncomplete() : undefined,
        backToList: companyKey ? backToList : undefined,
        onSelectSignal: (signalId) => {
          if (selectedCompany) lastSelection.current = { companyKey: selectedCompany.key, signalId }
          requestDetailFocus(signalId)
        },
        selectionFromList: readSelectionState(location.state)?.fromList ?? false,
        panelRef: detailPanelRef,
        copy,
        inaccessibleTitle: t.companyProfile.inaccessibleTitle,
        inaccessibleBody: t.companyProfile.inaccessibleBody,
        profileErrorTitle: t.companyProfile.errorTitle,
        profileErrorBody: t.companyProfile.errorBody,
        loading: t.reference.loading,
        emptyTitle: t.companiesIndex.emptyTitle,
        emptyBody: t.companiesIndex.emptyBody,
      })}
    </div>
  )
}

function renderDetail({
  access,
  companyKey,
  requestedSignalId,
  selectedCompany,
  selectedSignal,
  profile,
  profileKey,
  profileStatus,
  profileError,
  retryProfile,
  retryAccess,
  retryIncomplete,
  backToList,
  onSelectSignal,
  selectionFromList,
  panelRef,
  copy,
  inaccessibleTitle,
  inaccessibleBody,
  profileErrorTitle,
  profileErrorBody,
  loading,
  emptyTitle,
  emptyBody,
}: {
  access: AccessSnapshot
  companyKey: string | undefined
  requestedSignalId: string | null
  selectedCompany: AuthorizedCompany | null
  selectedSignal: AuthorizedCompanySignal | null
  profile: CompanyProfilePayload | null
  profileKey: string | null
  profileStatus: 'idle' | 'loading' | 'ready' | 'error'
  profileError: unknown
  retryProfile?: () => void
  retryAccess: () => void
  retryIncomplete?: () => void
  backToList?: () => void
  onSelectSignal: (signalId: string) => void
  selectionFromList: boolean
  panelRef: RefObject<HTMLElement | null>
  copy: ReturnType<typeof useI18n>['t']['reference']['companiesPage']
  inaccessibleTitle: string
  inaccessibleBody: string
  profileErrorTitle: string
  profileErrorBody: string
  loading: string
  emptyTitle: string
  emptyBody: string
}) {
  const message = (
    title: string,
    body: string,
    tone: 'status' | 'alert' | null = 'status',
    retry?: () => void,
    busy = false,
  ) => (
    <CompanyDetailMessage
      panelRef={panelRef}
      title={title}
      body={body}
      tone={tone}
      retry={retry}
      busy={busy}
      backToList={backToList}
    />
  )
  if (access.status === 'loading') return message(loading, copy.resolvingAccess)
  if (access.status === 'error') {
    return message(
      copy.resolutionError,
      copy.resolutionErrorBody,
      companyKey ? 'alert' : null,
      companyKey ? retryAccess : undefined,
    )
  }

  const incomplete = access.unresolved.length > 0
    || access.nextOffset !== null
    || access.scanTruncated
    || access.error !== null
  if (!companyKey) {
    if (access.companies.length === 0 && incomplete) {
      return message(copy.incompleteTitle, copy.incompleteBody, null)
    }
    if (access.companies.length === 0) return message(emptyTitle, emptyBody)
    return message(copy.noSelectionTitle, copy.noSelectionBody)
  }
  if (!selectedCompany) {
    if (incomplete) return message(copy.incompleteTitle, copy.incompleteBody, 'alert', retryIncomplete)
    return message(inaccessibleTitle, inaccessibleBody, 'alert')
  }
  if (!requestedSignalId || !selectedSignal) {
    if (incomplete) return message(copy.incompleteTitle, copy.incompleteBody, 'alert', retryIncomplete)
    return message(copy.awardInaccessibleTitle, copy.awardInaccessibleBody, 'alert')
  }
  if (
    profileKey !== selectedCompany.key
    || profileStatus === 'loading'
    || profileStatus === 'idle'
    || (profile !== null && profile.company_key !== selectedCompany.key)
  ) return message(
    selectedSignal.summary ?? copy.objectMissing,
    copy.loadingProfile,
    'status',
    undefined,
    true,
  )

  if (profileStatus === 'error' || !profile) {
    if (profileError instanceof ApiError && profileError.status === 404) {
      return message(inaccessibleTitle, inaccessibleBody, 'alert')
    }
    return message(profileErrorTitle, profileErrorBody, 'alert', retryProfile)
  }
  return (
    <CompanyProfileView
      panelRef={panelRef}
      profile={profile}
      company={selectedCompany}
      signal={selectedSignal}
      backToList={backToList}
      onSelectSignal={onSelectSignal}
      selectionFromList={selectionFromList}
    />
  )
}
