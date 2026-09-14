import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { signals } from '../api/endpoints'
import type { SignalStatusResult, UnifiedStatus } from '../api/types'
import { useProspecting } from './ProspectingProvider'

export interface ActionableSignal {
  signal_id: string
  status: UnifiedStatus
  status_revision?: number
}
interface StatusConflict { status: UnifiedStatus; revision: number }
interface ActionState {
  key: string
  pending: boolean
  committed: SignalStatusResult | null
  error: unknown | null
  conflict: StatusConflict | null
}

export function useSignalActions(signal: ActionableSignal | null, onCommitted?: (result: SignalStatusResult) => void) {
  const { accountId, accessEpoch, run, invalidate } = useProspecting()
  const key = JSON.stringify([accountId, signal?.signal_id, accessEpoch])
  const currentKey = useRef(key)
  currentKey.current = key
  const controller = useRef<AbortController | null>(null)
  const [state, setState] = useState<ActionState>({ key, pending: false, committed: null, error: null, conflict: null })
  useEffect(() => () => { controller.current?.abort(); controller.current = null }, [key])
  const committed = state.key === key && state.committed && state.committed.revision >= (signal?.status_revision ?? 0) ? state.committed : null
  const revision = committed?.revision ?? signal?.status_revision
  const status = committed?.status ?? signal?.status
  const setStatus = useCallback(async (next: UnifiedStatus) => {
    if (!signal || !Number.isSafeInteger(revision) || revision! < 0) throw new Error('Missing or invalid signal workflow revision')
    if (controller.current) throw new Error('A signal action is already pending')
    const requestController = new AbortController()
    controller.current = requestController
    setState({ key, pending: true, committed, error: null, conflict: null })
    try {
      const result = await run((abortSignal) => signals.setStatus(signal.signal_id, next, revision!, { signal: abortSignal }), requestController.signal)
      if (requestController.signal.aborted || currentKey.current !== key) return result
      if (result.signal_id !== signal.signal_id || result.status !== next || !Number.isSafeInteger(result.revision)
        || result.revision < revision! || (result.revision === revision && next !== status)) throw new Error('Invalid signal status response')
      setState({ key, pending: false, committed: result, error: null, conflict: null })
      invalidate()
      onCommitted?.(result)
      return result
    } catch (error) {
      if (!requestController.signal.aborted && currentKey.current === key) {
        const extra = error instanceof ApiError && error.status === 409 ? error.extra : null
        const conflict = extra && ['new', 'saved', 'contacted', 'ignored'].includes(String(extra.status)) && Number.isSafeInteger(extra.revision)
          ? { status: extra.status as UnifiedStatus, revision: extra.revision as number } : null
        setState({ key, pending: false, committed, error, conflict })
      }
      throw error
    } finally { if (controller.current === requestController) controller.current = null }
  }, [signal, revision, status, committed, key, run, invalidate, onCommitted])
  return { status, revision, setStatus, pending: state.key === key && state.pending, error: state.key === key ? state.error : null,
    conflict: state.key === key ? state.conflict : null, reload: invalidate }
}
