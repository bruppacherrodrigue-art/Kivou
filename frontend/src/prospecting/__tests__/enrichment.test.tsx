import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { companies } from '../../api/endpoints'
import { ApiError } from '../../api/client'
import type { CompanyDossierResponse, CompanyContactLookup } from '../../api/types'
import { useCompanyEnrichment } from '../useCompanyEnrichment'

const context = vi.hoisted(() => ({ accountId: 'a', accessEpoch: 0, invalidate: vi.fn(), run: vi.fn(async (load: (signal: AbortSignal) => Promise<unknown>, signal?: AbortSignal) => load(signal ?? new AbortController().signal)) }))
vi.mock('../ProspectingProvider', () => ({ useProspecting: () => context }))
const lookup: CompanyContactLookup = { state: 'researching', remaining: 4, monthly_quota: 5, source: 'apollo', removal_path: '/contact' }
const company = { company_key: 'alias', private_subject_key: 'private', capabilities: { can_view_company_data: true, can_enrich_company: true, can_lookup_contact: true, can_manage_personal_contact: true, can_take_notes: true, can_follow_company: true } }
beforeEach(() => vi.useFakeTimers())
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })

describe('bounded explicit company enrichment', () => {
  it('reads the current dossier when directory enrichment is already ready, preserving fresh lookup results', async () => {
    const post = vi.spyOn(companies, 'queueDirectoryEnrichment').mockResolvedValue({ queued: false, state: 'ready' })
    const get = vi.spyOn(companies, 'dossier').mockResolvedValue({ private_subject_key: 'private', directory: { siren: '123456789' }, contact_lookup: { ...lookup, state: 'ready' } } as CompanyDossierResponse)
    const { result } = renderHook(() => useCompanyEnrichment(company, { initialLookup: { ...lookup, state: 'ready' } }))
    await act(async () => { await result.current.startEnrichment() })
    expect(post).toHaveBeenCalledTimes(1)
    expect(get).toHaveBeenCalledTimes(1)
    expect(result.current.lookup?.state).toBe('ready')
  })
  it('does not consume quota or queue enrichment simply by mounting', async () => {
    const postLookup = vi.spyOn(companies, 'contactLookup')
    const postEnrich = vi.spyOn(companies, 'queueDirectoryEnrichment')
    const { unmount } = renderHook(() => useCompanyEnrichment(company))
    await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
    expect(postLookup).not.toHaveBeenCalled()
    expect(postEnrich).not.toHaveBeenCalled()
    unmount()
  })

  it('starts lookup once, uses only GET for bounded polling, and stops on a server result', async () => {
    const post = vi.spyOn(companies, 'contactLookup').mockResolvedValue(lookup)
    const get = vi.spyOn(companies, 'dossier').mockResolvedValue({ private_subject_key: 'private', contact_lookup: { ...lookup, state: 'ready' } } as CompanyDossierResponse)
    const { result } = renderHook(() => useCompanyEnrichment(company))
    await act(async () => { await result.current.startLookup() })
    expect(result.current.state).toBe('polling')
    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
    expect(result.current.state).toBe('ready')
    await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
    expect(post).toHaveBeenCalledTimes(1)
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('times out without inventing a contact and retry performs GET only', async () => {
    const post = vi.spyOn(companies, 'contactLookup').mockResolvedValue(lookup)
    const get = vi.spyOn(companies, 'dossier').mockResolvedValue({ private_subject_key: 'private', contact_lookup: lookup } as CompanyDossierResponse)
    const { result, unmount } = renderHook(() => useCompanyEnrichment(company))
    await act(async () => { await result.current.startLookup() })
    await act(async () => { await vi.advanceTimersByTimeAsync(32000) })
    expect(result.current.state).toBe('timeout')
    expect(get).toHaveBeenCalledTimes(15)
    await act(async () => { await result.current.refresh() })
    expect(get).toHaveBeenCalledTimes(16)
    expect(post).toHaveBeenCalledTimes(1)
    unmount()
  })

  it('aborts pending GET on close and refuses revoked capabilities', async () => {
    let pendingSignal: AbortSignal | undefined
    vi.spyOn(companies, 'contactLookup').mockResolvedValue(lookup)
    vi.spyOn(companies, 'dossier').mockImplementation((_key, options) => { pendingSignal = options?.signal; return new Promise(() => {}) })
    const { result, unmount } = renderHook(() => useCompanyEnrichment(company))
    await act(async () => { await result.current.startLookup() })
    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
    unmount()
    expect(pendingSignal?.aborted).toBe(true)
    const denied = renderHook(() => useCompanyEnrichment({ ...company, capabilities: { ...company.capabilities, can_lookup_contact: false } }))
    await act(async () => { await expect(denied.result.current.startLookup()).rejects.toThrow('not permitted') })
  })

  it('refreshes authority with GET after quota exhaustion without repeating the paid POST', async () => {
    const post = vi.spyOn(companies, 'contactLookup').mockRejectedValue(new ApiError(403, 'contact_lookup_quota_exhausted', ''))
    const get = vi.spyOn(companies, 'dossier').mockResolvedValue({ private_subject_key: 'private', contact_lookup: { ...lookup, state: 'ready', remaining: 0, can_refresh: false } } as CompanyDossierResponse)
    const { result } = renderHook(() => useCompanyEnrichment(company))
    await act(async () => { await result.current.startLookup() })
    expect(get).toHaveBeenCalledTimes(1)
    expect(post).toHaveBeenCalledTimes(1)
    expect(result.current.lookup).toMatchObject({ state: 'ready', remaining: 0, can_refresh: false })
  })
})
