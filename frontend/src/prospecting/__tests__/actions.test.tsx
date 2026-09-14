import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { companies, signals } from '../../api/endpoints'
import type { CompanyCapabilities, SignalStatusResult } from '../../api/types'
import { useSignalActions } from '../useSignalActions'
import { useCompanyActions } from '../useCompanyActions'

const context = vi.hoisted(() => ({ accountId: 'a', accessEpoch: 0, invalidate: vi.fn(), run: vi.fn(async (load: (signal: AbortSignal) => Promise<unknown>, signal?: AbortSignal) => load(signal ?? new AbortController().signal)) }))
vi.mock('../ProspectingProvider', () => ({ useProspecting: () => context }))
afterEach(() => vi.restoreAllMocks())
const capabilities: CompanyCapabilities = { can_view_company_data: false, can_enrich_company: false, can_lookup_contact: false, can_manage_personal_contact: true, can_take_notes: true, can_follow_company: true }
const company = { company_key: 'requested-isolated-alias', private_subject_key: 'private-isolated', capabilities }
const response: SignalStatusResult = { signal_id: 's', status: 'saved', revision: 8, updated_at: '2026-09-13T10:00:00Z', interaction: null }

describe('reversible signal actions', () => {
  it('accepts an idempotent server acknowledgement only for the already current status', async () => {
    vi.spyOn(signals, 'setStatus').mockResolvedValue(response)
    const { result } = renderHook(() => useSignalActions({ signal_id: 's', status: 'saved', status_revision: 8 }))
    await act(async () => { await expect(result.current.setStatus('saved')).resolves.toEqual(response) })
    expect(result.current.error).toBeNull()
  })

  it.each([
    { revision: 7 }, { revision: 8 }, { revision: 8.5 }, { revision: Number.NaN },
    { revision: 9, status: 'ignored' }, { revision: 9, signal_id: 'another' },
  ])('rejects a stale or malformed acknowledgement %j', async (patch) => {
    vi.spyOn(signals, 'setStatus').mockResolvedValue({ ...response, ...patch } as SignalStatusResult)
    const { result } = renderHook(() => useSignalActions({ signal_id: 's', status: 'new', status_revision: 8 }))
    await act(async () => { await expect(result.current.setStatus('saved')).rejects.toThrow('Invalid signal status response') })
    expect(result.current.status).toBe('new')
  })
  it('uses status_revision, confirms the server value and invalidates shared views only on success', async () => {
    const write = vi.spyOn(signals, 'setStatus').mockResolvedValue(response)
    context.invalidate.mockClear()
    const { result } = renderHook(() => useSignalActions({ signal_id: 's', status: 'new', status_revision: 7 }))
    await act(async () => { await result.current.setStatus('saved') })
    expect(write).toHaveBeenCalledWith('s', 'saved', 7, expect.anything())
    expect(result.current.status).toBe('saved')
    expect(result.current.revision).toBe(8)
    expect(context.invalidate).toHaveBeenCalledTimes(1)
  })

  it('never guesses a missing workflow revision', async () => {
    const write = vi.spyOn(signals, 'setStatus')
    const { result } = renderHook(() => useSignalActions({ signal_id: 's', status: 'new' }))
    await act(async () => { await expect(result.current.setStatus('saved')).rejects.toThrow('revision') })
    expect(write).not.toHaveBeenCalled()
  })

  it('preserves the last status on conflict and never retries automatically', async () => {
    const error = new ApiError(409, 'status_conflict', '', { status: 'contacted', revision: 9 })
    const write = vi.spyOn(signals, 'setStatus').mockRejectedValue(error)
    const { result } = renderHook(() => useSignalActions({ signal_id: 's', status: 'new', status_revision: 7 }))
    await act(async () => { await expect(result.current.setStatus('saved')).rejects.toBe(error) })
    expect(result.current.status).toBe('new')
    expect(result.current.conflict).toMatchObject({ status: 'contacted', revision: 9 })
    expect(write).toHaveBeenCalledTimes(1)
  })
})

describe('private company actions', () => {
  it('allows personal contact on discovery and sends the requested alias, never the public identity', async () => {
    const contact = { contact: { name: 'Claire', role: null, email: 'c@example.test', phone: null, source: 'user' as const }, revision: 1, updated_at: null }
    const write = vi.spyOn(companies, 'saveManualContact').mockResolvedValue(contact)
    const { result } = renderHook(() => useCompanyActions(company))
    await act(async () => { await result.current.saveContact({ name: 'Claire', email: 'c@example.test', expected_revision: 0 }) })
    expect(write).toHaveBeenCalledWith('requested-isolated-alias', { name: 'Claire', email: 'c@example.test', expected_revision: 0 }, expect.anything())
  })

  it('preserves manual contact conflicts for explicit comparison without overwriting', async () => {
    const error = new ApiError(409, 'manual_contact_conflict', '', { contact: null, revision: 4, updated_at: null })
    const write = vi.spyOn(companies, 'deleteManualContact').mockRejectedValue(error)
    const { result } = renderHook(() => useCompanyActions(company))
    await act(async () => { await expect(result.current.deleteContact(3)).rejects.toBe(error) })
    expect(result.current.contactConflict).toEqual({ contact: null, revision: 4, updated_at: null })
    expect(write).toHaveBeenCalledTimes(1)
  })

  it('refuses a capability denied by the dossier even when another action is allowed', async () => {
    const write = vi.spyOn(companies, 'follow')
    const { result } = renderHook(() => useCompanyActions({ ...company, capabilities: { ...capabilities, can_follow_company: false } }))
    await act(async () => { await expect(result.current.follow()).rejects.toThrow('not permitted') })
    expect(write).not.toHaveBeenCalled()
  })
})
