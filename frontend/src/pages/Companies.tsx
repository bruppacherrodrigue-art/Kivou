import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { MVP_TERRITORIES, territoryLabel } from '../api/capabilities'
import { companies, signals } from '../api/endpoints'
import { ApiError } from '../api/client'
import type {
  CompanyProfile as CompanyProfilePayload,
  UnlockedDetail,
  UnlockedFeedItem,
} from '../api/types'
import { interpolate, plural, useI18n } from '../i18n'
import {
  type AuthorizedCompany,
  type AuthorizedCompanySignal,
  CompanyDetailMessage,
  CompanyProfileView,
  companyInitials,
} from './CompanyProfile'

const FEED_LIMIT = 20
const DETAIL_CONCURRENCY = 4

interface AccessSnapshot {
  status: 'loading' | 'ready' | 'error'
  companies: AuthorizedCompany[]
  details: Map<string, UnlockedDetail>
  unresolved: UnlockedFeedItem[]
  nextOffset: number | null
  scanTruncated: boolean
  error: unknown | null
  retrying: boolean
}

const INITIAL_ACCESS: AccessSnapshot = {
  status: 'loading',
  companies: [],
  details: new Map(),
  unresolved: [],
  nextOffset: null,
  scanTruncated: false,
  error: null,
  retrying: false,
}

interface DetailResult {
  item: UnlockedFeedItem
  detail: UnlockedDetail | null
  failed: boolean
}

async function boundedDetails(
  items: UnlockedFeedItem[],
  isCurrent: () => boolean,
): Promise<DetailResult[]> {
  const results: DetailResult[] = new Array(items.length)
  let cursor = 0
  const worker = async () => {
    while (cursor < items.length && isCurrent()) {
      const index = cursor
      cursor += 1
      const item = items[index]
      try {
        const payload = await signals.detail(item.signal_id)
        results[index] = {
          item,
          detail: payload.locked === false ? payload as UnlockedDetail : null,
          failed: false,
        }
      } catch {
        results[index] = { item, detail: null, failed: true }
      }
    }
  }
  await Promise.all(Array.from(
    { length: Math.min(DETAIL_CONCURRENCY, items.length) },
    () => worker(),
  ))
  return results
}

function companiesFrom(
  orderedItems: UnlockedFeedItem[],
  details: Map<string, UnlockedDetail>,
): AuthorizedCompany[] {
  const grouped = new Map<string, AuthorizedCompany>()
  for (const item of orderedItems) {
    const detail = details.get(item.signal_id)
    if (!detail || detail.locked || !detail.company_key || !detail.company.name) continue
    const signal: AuthorizedCompanySignal = {
      signalId: detail.signal_id,
      title: detail.contract.title,
      amountValue: detail.contract.amount?.value ?? null,
      amountCurrency: detail.contract.amount?.currency ?? null,
      awardDate: detail.contract.dates.award,
    }
    const existing = grouped.get(detail.company_key)
    if (existing) {
      if (!existing.signals.some((candidate) => candidate.signalId === signal.signalId)) {
        existing.signals.push(signal)
      }
      continue
    }
    grouped.set(detail.company_key, {
      key: detail.company_key,
      name: detail.company.name,
      country: detail.company.country,
      signals: [signal],
    })
  }
  return [...grouped.values()]
}

export function Companies() {
  const { companyKey } = useParams()
  const navigate = useNavigate()
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
  const pendingMobileFocus = useRef<string | null>(null)
  const [mobileFocusRequest, setMobileFocusRequest] = useState(0)

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

    const detailResults = await boundedDetails(orderedItemsRef.current, isCurrent)
    if (!isCurrent()) return
    const details = new Map<string, UnlockedDetail>()
    const unresolved: UnlockedFeedItem[] = []
    for (const result of detailResults) {
      if (result.detail) details.set(result.item.signal_id, result.detail)
      else if (result.failed) unresolved.push(result.item)
    }
    const resolvedCompanies = companiesFrom(orderedItemsRef.current, details)
    if (resolvedCompanies.length === 0 && unresolved.length > 0 && !pageFailure && !scanTruncated) {
      publishAccess({
        status: 'error', companies: [], details, unresolved, nextOffset,
        scanTruncated, error: new Error('company_details_unavailable'), retrying: false,
      })
      return
    }
    publishAccess({
      status: 'ready',
      companies: resolvedCompanies,
      details,
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
    const generation = ++accessGeneration.current
    const isCurrent = () => mounted.current && accessGeneration.current === generation
    publishAccess({ ...previous, retrying: true })
    const details = new Map(previous.details)
    const unresolvedById = new Map(previous.unresolved.map((item) => [item.signal_id, item]))
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
          unresolvedById.set(item.signal_id, item)
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

    const retried = await boundedDetails([...unresolvedById.values()], isCurrent)
    if (!isCurrent()) return
    const stillUnresolved: UnlockedFeedItem[] = []
    for (const result of retried) {
      if (result.detail) details.set(result.item.signal_id, result.detail)
      else if (result.failed) stillUnresolved.push(result.item)
    }
    const resolvedCompanies = companiesFrom(orderedItemsRef.current, details)
    publishAccess({
      status: resolvedCompanies.length === 0 && stillUnresolved.length > 0 && !pageFailure && !scanTruncated
        ? 'error'
        : 'ready',
      companies: resolvedCompanies,
      details,
      unresolved: stillUnresolved,
      nextOffset,
      scanTruncated,
      error: pageFailure ?? (resolvedCompanies.length === 0 && stillUnresolved.length > 0
        ? new Error('company_details_unavailable')
        : null),
      retrying: false,
    })
  }, [publishAccess])

  const selectedCompany = useMemo(() => {
    const key = companyKey ?? access.companies[0]?.key
    return key ? access.companies.find((candidate) => candidate.key === key) ?? null : null
  }, [access.companies, companyKey])
  const selectedKey = selectedCompany?.key ?? null

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

  const selectCompany = (key: string) => {
    if (window.innerWidth < 1180) {
      pendingMobileFocus.current = key
      setMobileFocusRequest((current) => current + 1)
    }
    navigate(`/app/companies/${encodeURIComponent(key)}`, { replace: true })
  }

  useEffect(() => {
    if (
      !selectedKey ||
      pendingMobileFocus.current !== selectedKey ||
      profileKey !== selectedKey ||
      (profileStatus !== 'ready' && profileStatus !== 'error')
    ) return
    const frame = window.requestAnimationFrame(() => {
      const detail = document.getElementById('company-detail')
      if (typeof detail?.scrollIntoView === 'function') {
        detail.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
      detail?.focus({ preventScroll: true })
      pendingMobileFocus.current = null
    })
    return () => window.cancelAnimationFrame(frame)
  }, [mobileFocusRequest, profileKey, profileStatus, selectedKey])

  const partial = access.status === 'ready' && (
    access.unresolved.length > 0 || access.nextOffset !== null || access.scanTruncated || access.error !== null
  )
  const copy = t.reference.companiesPage

  return (
    <div className="companies-workspace">
      <aside className="companies-panel" aria-labelledby="companies-list-title">
        <div className="panel-heading">
          <div>
            <p className="section-label">{copy.publishedHolders}</p>
            <h2 id="companies-list-title">{t.reference.headings.linkedCompanies}</h2>
          </div>
          <span className="signal-count">{access.status === 'loading' ? '…' : access.companies.length}</span>
        </div>
        <p className="companies-panel-note">{copy.listBoundary} {t.companiesIndex.partial}</p>

        {access.status === 'error' ? (
          <div role="alert" className="companies-panel-note">
            <strong>{t.companiesIndex.errorTitle}</strong>
            <button type="button" onClick={() => void loadAccess()}>{t.reference.retry}</button>
          </div>
        ) : null}
        {partial ? (
          <div role="alert" className="companies-panel-note">
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

        <div className="companies-list">
          {access.status === 'ready' && access.companies.length === 0 && !partial
            ? <p className="companies-panel-note">{t.companiesIndex.emptyTitle}</p>
            : null}
          {access.companies.map((company) => {
            const latest = company.signals[0]
            const selected = company.key === selectedKey
            const knownTerritory = MVP_TERRITORIES.find((candidate) => candidate.code === company.country)
            const localizedCountry = knownTerritory
              ? territoryLabel(knownTerritory, locale)
              : company.country ?? t.reference.missingValue
            const publishedAmount = latest
              ? amount(latest.amountValue, latest.amountCurrency) ?? t.reference.missingValue
              : t.reference.missingValue
            const publishedDate = latest ? date(latest.awardDate) ?? t.reference.missingValue : t.reference.missingValue
            const count = company.signals.length
            return (
              <button
                type="button"
                className={`company-list-item${selected ? ' is-selected' : ''}`}
                aria-pressed={selected}
                onClick={() => selectCompany(company.key)}
                key={company.key}
              >
                <span className="company-list-avatar" aria-hidden="true">{companyInitials(company.name)}</span>
                <span className="company-list-content">
                  <span className="company-list-heading">
                    <strong>{company.name}</strong>
                    <span>{interpolate(plural(count, copy.contractOne, copy.contractOther), { count })}</span>
                  </span>
                  <span className="company-list-location">{localizedCountry}</span>
                  <span className="company-list-event">{latest?.title ?? t.reference.missingValue}</span>
                  <span className="company-list-meta"><span>{publishedAmount}</span><span>{publishedDate}</span></span>
                </span>
              </button>
            )
          })}
        </div>
      </aside>

      {renderDetail({
        access,
        companyKey,
        selectedCompany,
        profile,
        profileKey,
        profileStatus,
        profileError,
        retryProfile: selectedKey ? () => void loadProfile(selectedKey) : undefined,
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
  selectedCompany,
  profile,
  profileKey,
  profileStatus,
  profileError,
  retryProfile,
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
  selectedCompany: AuthorizedCompany | null
  profile: CompanyProfilePayload | null
  profileKey: string | null
  profileStatus: 'idle' | 'loading' | 'ready' | 'error'
  profileError: unknown
  retryProfile?: () => void
  copy: ReturnType<typeof useI18n>['t']['reference']['companiesPage']
  inaccessibleTitle: string
  inaccessibleBody: string
  profileErrorTitle: string
  profileErrorBody: string
  loading: string
  emptyTitle: string
  emptyBody: string
}) {
  if (access.status === 'loading') return <CompanyDetailMessage title={loading} body={copy.resolvingAccess} />
  if (access.status === 'error') return <CompanyDetailMessage title={copy.resolutionError} body={copy.resolutionErrorBody} tone={null} />
  if (!selectedCompany) {
    const incomplete = access.unresolved.length > 0 || access.nextOffset !== null || access.scanTruncated || access.error !== null
    if (incomplete) {
      return <CompanyDetailMessage title={copy.incompleteTitle} body={copy.incompleteBody} tone={null} />
    }
    return <CompanyDetailMessage
      title={companyKey ? inaccessibleTitle : emptyTitle}
      body={companyKey ? inaccessibleBody : emptyBody}
      tone={companyKey ? 'alert' : 'status'}
    />
  }
  if (
    profileKey !== selectedCompany.key ||
    profileStatus === 'loading' ||
    profileStatus === 'idle' ||
    (profile !== null && profile.company_key !== selectedCompany.key)
  ) {
    return <CompanyDetailMessage title={loading} body={copy.loadingProfile} />
  }
  if (profileStatus === 'error' || !profile) {
    if (profileError instanceof ApiError && profileError.status === 404) {
      return <CompanyDetailMessage title={inaccessibleTitle} body={inaccessibleBody} tone="alert" />
    }
    return <CompanyDetailMessage title={profileErrorTitle} body={profileErrorBody} retry={retryProfile} tone="alert" />
  }
  return <CompanyProfileView profile={profile} />
}
