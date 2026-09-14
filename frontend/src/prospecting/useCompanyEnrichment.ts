import { useCallback, useEffect, useRef, useState } from 'react'
import { companies } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { CompanyContactLookup, CompanyDirectoryEnrichment, CompanyDossierResponse } from '../api/types'
import { useProspecting } from './ProspectingProvider'
import type { ActionableCompany } from './useCompanyActions'

type EnrichmentMode = 'directory' | 'lookup'
type EnrichmentState = 'idle' | 'requesting' | 'polling' | 'waiting' | 'ready' | 'timeout' | 'error'
interface Snapshot {
  key: string
  state: EnrichmentState
  lookup: CompanyContactLookup | null
  directoryEnrichment: CompanyDirectoryEnrichment | null
  dossier: CompanyDossierResponse | null
  error: unknown | null
}
const POLL_INTERVAL_MS = 2000
const MAX_POLLS = 15
const directoryPending = (state?: CompanyDirectoryEnrichment['state']) => !!state && ['queued', 'running', 'budget_wait'].includes(state)
const directoryTerminal = (value?: CompanyDirectoryEnrichment | null) => !!value && ['ready', 'partial', 'failed', 'identity_unavailable', 'locked'].includes(value.state)
const revokesLookup = (error: unknown) => error instanceof ApiError && (error.status === 401 || ['contact_lookup_suppressed', 'contact_lookup_identity_unavailable', 'contact_lookup_locked'].includes(error.code))

/** Paid POSTs are explicit. Polling/retry only reads and never consumes another lookup. */
export function useCompanyEnrichment(company: ActionableCompany | null, options: {
  initialLookup?: CompanyContactLookup | null
  initialDirectoryEnrichment?: CompanyDirectoryEnrichment | null
  onUpdated?: (dossier: CompanyDossierResponse) => void
} = {}) {
  const { accountId, accessEpoch, run, invalidate } = useProspecting()
  const key = JSON.stringify([accountId, company?.company_key, company?.private_subject_key, accessEpoch])
  const currentKey = useRef(key)
  currentKey.current = key
  const currentCompany = useRef(company)
  currentCompany.current = company
  const hasCompany = company !== null
  const onUpdated = useRef(options.onUpdated)
  onUpdated.current = options.onUpdated
  const controller = useRef<AbortController | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mode = useRef<EnrichmentMode>('lookup')
  const sequence = useRef(0)
  const invalidateOnClose = useRef(false)
  const [snapshot, setSnapshot] = useState<Snapshot>({ key, state: 'idle', lookup: options.initialLookup ?? null, directoryEnrichment: options.initialDirectoryEnrichment ?? null, dossier: null, error: null })
  const stop = useCallback(() => {
    sequence.current += 1
    if (timer.current !== null) clearTimeout(timer.current)
    timer.current = null
    controller.current?.abort()
    controller.current = null
  }, [])
  useEffect(() => () => {
    stop()
    // Update the open dossier in place. Global invalidation would unmount its
    // private contact editor and lose an unsaved draft; refresh other views on close.
    if (invalidateOnClose.current) { invalidateOnClose.current = false; invalidate() }
  }, [key, stop, invalidate])

  const read = useCallback(async function poll(pollMode: EnrichmentMode, attempt: number, generation: number): Promise<void> {
    const identity = currentCompany.current
    if (!identity || generation !== sequence.current || currentKey.current !== key) return
    const requestController = new AbortController()
    controller.current = requestController
    try {
      const dossier = await run((signal) => companies.dossier(identity.company_key, { signal }), requestController.signal)
      if (generation !== sequence.current || requestController.signal.aborted || currentKey.current !== key) return
      if (dossier.private_subject_key !== identity.private_subject_key) throw new Error('Private company identity changed; reopen the dossier')
      const lookup = dossier.contact_lookup ?? null
      const directoryEnrichment = dossier.directory_enrichment ?? null
      const ready = pollMode === 'lookup' ? !!lookup && lookup.state !== 'researching' : directoryTerminal(directoryEnrichment)
      setSnapshot({ key, dossier, lookup, directoryEnrichment, state: ready ? 'ready' : attempt >= MAX_POLLS ? pollMode === 'directory' ? 'waiting' : 'timeout' : 'polling', error: null })
      if (ready) { invalidateOnClose.current = true; onUpdated.current?.(dossier) }
      else if (attempt < MAX_POLLS) timer.current = setTimeout(() => { timer.current = null; void poll(pollMode, attempt + 1, generation) }, POLL_INTERVAL_MS)
    } catch (error) {
      if (generation === sequence.current && !requestController.signal.aborted && currentKey.current === key) setSnapshot((current) => ({ ...current, key, state: 'error', lookup: revokesLookup(error) ? null : current.lookup, dossier: revokesLookup(error) ? null : current.dossier, error }))
    } finally { if (controller.current === requestController) controller.current = null }
  }, [key, run])
  const start = useCallback(async (nextMode: EnrichmentMode) => {
    if (!company || !company.capabilities[nextMode === 'lookup' ? 'can_lookup_contact' : 'can_enrich_company']) throw new Error('Company enrichment not permitted by the dossier')
    if (controller.current || timer.current !== null) throw new Error('Company enrichment is already pending')
    mode.current = nextMode
    const generation = ++sequence.current
    const requestController = new AbortController()
    controller.current = requestController
    setSnapshot((current) => ({ ...current, key, state: 'requesting', error: null }))
    try {
      let complete = false
      let lookup: CompanyContactLookup | null = snapshot.key === key ? snapshot.lookup : options.initialLookup ?? null
      let directoryEnrichment = snapshot.key === key ? snapshot.directoryEnrichment : options.initialDirectoryEnrichment ?? null
      if (nextMode === 'lookup') {
        lookup = await run((signal) => companies.contactLookup(company.company_key, { signal }), requestController.signal)
        complete = lookup.state !== 'researching'
      } else {
        const result = await run((signal) => companies.queueDirectoryEnrichment(company.company_key, { signal }), requestController.signal)
        directoryEnrichment = result
        complete = directoryTerminal(result)
      }
      if (generation !== sequence.current || requestController.signal.aborted || currentKey.current !== key) return
      if (complete && nextMode === 'directory') {
        // The queue endpoint does not carry contacts. Read the authoritative
        // dossier before replacing the previous lookup with a ready snapshot.
        await read('directory', MAX_POLLS, generation)
        return
      }
      setSnapshot((current) => ({ ...current, key, state: complete ? 'ready' : 'polling', lookup, directoryEnrichment, error: null }))
      if (complete) invalidateOnClose.current = true
      else timer.current = setTimeout(() => { timer.current = null; void read(nextMode, 1, generation) }, POLL_INTERVAL_MS)
    } catch (error) {
      if (generation === sequence.current && !requestController.signal.aborted && currentKey.current === key
        && error instanceof ApiError && error.code === 'contact_lookup_quota_exhausted') {
        await read('lookup', MAX_POLLS, generation)
        return
      }
      if (generation === sequence.current && !requestController.signal.aborted && currentKey.current === key) setSnapshot((current) => ({ ...current, key, state: 'error', lookup: revokesLookup(error) ? null : current.lookup, dossier: revokesLookup(error) ? null : current.dossier, error }))
      throw error
    } finally { if (controller.current === requestController) controller.current = null }
  }, [company, key, run, read, snapshot.key, snapshot.lookup, snapshot.directoryEnrichment, options.initialLookup, options.initialDirectoryEnrichment])
  const refresh = useCallback(async () => { stop(); await read(mode.current, 1, sequence.current) }, [stop, read])
  // Reopening an already-running lookup resumes reads, never a second POST.
  useEffect(() => {
    const resumeMode = directoryPending(options.initialDirectoryEnrichment?.state) ? 'directory' : options.initialLookup?.state === 'researching' ? 'lookup' : null
    if (!resumeMode || !hasCompany) return
    mode.current = resumeMode
    const generation = sequence.current
    timer.current = setTimeout(() => { timer.current = null; void read(resumeMode, 1, generation) }, POLL_INTERVAL_MS)
    return stop
  }, [key, options.initialLookup?.state, options.initialDirectoryEnrichment?.state, options.initialDirectoryEnrichment?.job_id, hasCompany, read, stop])
  return {
    ...(snapshot.key === key ? snapshot : { key, state: 'idle' as const, lookup: options.initialLookup ?? null, directoryEnrichment: options.initialDirectoryEnrichment ?? null, dossier: null, error: null }),
    startLookup: () => start('lookup'), startEnrichment: () => start('directory'), refresh,
  }
}
