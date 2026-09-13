import { useCallback, useEffect, useRef, useState } from 'react'
import { companies } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { CompanyContactLookup, CompanyDossierResponse } from '../api/types'
import { useProspecting } from './ProspectingProvider'
import type { ActionableCompany } from './useCompanyActions'

type EnrichmentMode = 'directory' | 'lookup'
type EnrichmentState = 'idle' | 'requesting' | 'polling' | 'ready' | 'timeout' | 'error'
interface Snapshot {
  key: string
  state: EnrichmentState
  lookup: CompanyContactLookup | null
  dossier: CompanyDossierResponse | null
  error: unknown | null
}
const POLL_INTERVAL_MS = 2000
const MAX_POLLS = 15

/** Paid POSTs are explicit. Polling/retry only reads and never consumes another lookup. */
export function useCompanyEnrichment(company: ActionableCompany | null, options: {
  initialLookup?: CompanyContactLookup | null
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
  const [snapshot, setSnapshot] = useState<Snapshot>({ key, state: 'idle', lookup: options.initialLookup ?? null, dossier: null, error: null })
  const stop = useCallback(() => {
    sequence.current += 1
    if (timer.current !== null) clearTimeout(timer.current)
    timer.current = null
    controller.current?.abort()
    controller.current = null
  }, [])
  useEffect(() => () => stop(), [key, stop])

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
      const ready = pollMode === 'lookup' ? !!lookup && lookup.state !== 'researching' : !!dossier.directory
      setSnapshot({ key, dossier, lookup, state: ready ? 'ready' : attempt >= MAX_POLLS ? 'timeout' : 'polling', error: null })
      if (ready) { onUpdated.current?.(dossier); invalidate() }
      else if (attempt < MAX_POLLS) timer.current = setTimeout(() => { timer.current = null; void poll(pollMode, attempt + 1, generation) }, POLL_INTERVAL_MS)
    } catch (error) {
      if (generation === sequence.current && !requestController.signal.aborted && currentKey.current === key) setSnapshot((current) => ({ ...current, key, state: 'error', error }))
    } finally { if (controller.current === requestController) controller.current = null }
  }, [key, run, invalidate])
  const start = useCallback(async (nextMode: EnrichmentMode) => {
    if (!company || !company.capabilities[nextMode === 'lookup' ? 'can_lookup_contact' : 'can_enrich_company']) throw new Error('Company enrichment not permitted by the dossier')
    if (controller.current || timer.current !== null) throw new Error('Company enrichment is already pending')
    mode.current = nextMode
    const generation = ++sequence.current
    const requestController = new AbortController()
    controller.current = requestController
    setSnapshot({ key, state: 'requesting', lookup: null, dossier: null, error: null })
    try {
      let complete = false
      let lookup: CompanyContactLookup | null = null
      if (nextMode === 'lookup') {
        lookup = await run((signal) => companies.contactLookup(company.company_key, { signal }), requestController.signal)
        complete = lookup.state !== 'researching'
      } else {
        const result = await run((signal) => companies.queueDirectoryEnrichment(company.company_key, { signal }), requestController.signal)
        complete = result.state === 'ready'
      }
      if (generation !== sequence.current || requestController.signal.aborted || currentKey.current !== key) return
      if (complete && nextMode === 'directory') {
        // The queue endpoint does not carry contacts. Read the authoritative
        // dossier before replacing the previous lookup with a ready snapshot.
        await read('directory', MAX_POLLS, generation)
        return
      }
      setSnapshot({ key, state: complete ? 'ready' : 'polling', lookup, dossier: null, error: null })
      if (complete) invalidate()
      else timer.current = setTimeout(() => { timer.current = null; void read(nextMode, 1, generation) }, POLL_INTERVAL_MS)
    } catch (error) {
      if (generation === sequence.current && !requestController.signal.aborted && currentKey.current === key
        && error instanceof ApiError && error.code === 'contact_lookup_quota_exhausted') {
        await read('lookup', MAX_POLLS, generation)
        return
      }
      if (generation === sequence.current && !requestController.signal.aborted && currentKey.current === key) setSnapshot((current) => ({ ...current, key, state: 'error', error }))
      throw error
    } finally { if (controller.current === requestController) controller.current = null }
  }, [company, key, run, read, invalidate])
  const refresh = useCallback(async () => { stop(); await read(mode.current, 1, sequence.current) }, [stop, read])
  // Reopening an already-running lookup resumes reads, never a second POST.
  useEffect(() => {
    if (options.initialLookup?.state !== 'researching' || !hasCompany) return
    const generation = sequence.current
    timer.current = setTimeout(() => { timer.current = null; void read('lookup', 1, generation) }, POLL_INTERVAL_MS)
    return stop
  }, [key, options.initialLookup?.state, hasCompany, read, stop])
  return {
    ...(snapshot.key === key ? snapshot : { key, state: 'idle' as const, lookup: options.initialLookup ?? null, dossier: null, error: null }),
    startLookup: () => start('lookup'), startEnrichment: () => start('directory'), refresh,
  }
}
