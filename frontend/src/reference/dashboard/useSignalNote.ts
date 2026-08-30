import { useCallback, useEffect, useRef, useState } from 'react'
import { signalNotes } from '../../api/endpoints'

export type NoteSaveState =
  | 'idle'
  | 'loading'
  | 'saving'
  | 'saved'
  | 'read-error'
  | 'write-error'

interface NoteContext {
  accountId: string
  signalKey: string | null
  enabled: boolean
  generation: number
}

interface PendingWrite {
  snapshot: NoteContext
  requestId: number
  value: string
}

interface SignalNoteController {
  value: string
  state: NoteSaveState
  error: unknown | null
  change: (value: string) => void
  flush: () => void
  retry: () => void
}

function sameContext(left: NoteContext, right: NoteContext): boolean {
  return left.accountId === right.accountId
    && left.signalKey === right.signalKey
    && left.enabled === right.enabled
    && left.generation === right.generation
}

export function useSignalNote({
  accountId,
  signalKey,
  enabled,
}: {
  accountId: string
  signalKey: string | null
  enabled: boolean
}): SignalNoteController {
  const [value, setValue] = useState('')
  const [state, setState] = useState<NoteSaveState>('idle')
  const [error, setError] = useState<unknown | null>(null)
  const [loadedContextGeneration, setLoadedContextGeneration] = useState<number | null>(null)
  const mounted = useRef(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const context = useRef<NoteContext>({ accountId, signalKey, enabled, generation: 0 })
  const valueRef = useRef('')
  const readRequest = useRef(0)
  const writeRequest = useRef(0)
  const hasLoaded = useRef(false)
  const inFlightWrite = useRef<PendingWrite | null>(null)
  const queuedWrites = useRef<PendingWrite[]>([])
  const scheduledWrite = useRef<PendingWrite | null>(null)
  const latestAccountId = useRef(accountId)
  latestAccountId.current = accountId

  const cancelTimer = useCallback(() => {
    if (timer.current !== null) {
      clearTimeout(timer.current)
      timer.current = null
    }
    scheduledWrite.current = null
  }, [])

  const isCurrent = useCallback((snapshot: NoteContext) => {
    const current = context.current
    return mounted.current
      && current.generation === snapshot.generation
      && current.accountId === snapshot.accountId
      && current.signalKey === snapshot.signalKey
      && current.enabled === snapshot.enabled
  }, [])

  const persist = useCallback(
    async function persistInOrder(pending: PendingWrite) {
      const { snapshot, requestId, value: nextValue } = pending
      if (!snapshot.signalKey) return
      inFlightWrite.current = pending

      let savedValue: string | null = null
      let failure: unknown | null = null
      try {
        const saved = await signalNotes.write(snapshot.signalKey, nextValue)
        savedValue = saved.note ?? ''
      } catch (cause) {
        failure = cause
      }

      if (inFlightWrite.current !== pending) return
      inFlightWrite.current = null

      const next = queuedWrites.current.shift()
      if (next) {
        void persistInOrder(next)
        return
      }

      if (!isCurrent(snapshot)) return

      // Une frappe plus récente peut encore être dans sa fenêtre de debounce.
      // La réponse courante ne doit alors ni réécrire la textarea ni annoncer
      // un succès/échec qui ne concerne plus la valeur visible.
      if (requestId !== writeRequest.current) return
      if (failure !== null) {
        setState('write-error')
        setError(failure)
        return
      }

      const serverValue = savedValue ?? ''
      valueRef.current = serverValue
      setValue(serverValue)
      setState('saved')
      setError(null)
    },
    [isCurrent],
  )

  const enqueue = useCallback((pending: PendingWrite) => {
    const active = inFlightWrite.current
    if (active) {
      // Les écritures restent globalement sérialisées. Pour un même contexte,
      // seule la dernière valeur attend ; les brouillons d'autres signaux ne
      // s'écrasent jamais lors d'une navigation rapide.
      const existing = queuedWrites.current.findIndex((queued) =>
        sameContext(queued.snapshot, pending.snapshot),
      )
      if (existing === -1) queuedWrites.current.push(pending)
      else queuedWrites.current[existing] = pending
      return
    }
    inFlightWrite.current = null
    void persist(pending)
  }, [persist])

  const flush = useCallback(() => {
    const pending = scheduledWrite.current
    if (!pending) return
    if (timer.current !== null) {
      clearTimeout(timer.current)
      timer.current = null
    }
    scheduledWrite.current = null
    enqueue(pending)
  }, [enqueue])

  const load = useCallback((snapshot: NoteContext) => {
    if (!snapshot.enabled || !snapshot.signalKey) return
    const requestId = ++readRequest.current
    setState('loading')
    setError(null)
    signalNotes.read(snapshot.signalKey).then(
      (loaded) => {
        if (!isCurrent(snapshot) || requestId !== readRequest.current) return
        const loadedValue = loaded.note ?? ''
        hasLoaded.current = true
        setLoadedContextGeneration(snapshot.generation)
        valueRef.current = loadedValue
        setValue(loadedValue)
        setState('idle')
        setError(null)
      },
      (cause) => {
        if (!isCurrent(snapshot) || requestId !== readRequest.current) return
        hasLoaded.current = false
        setLoadedContextGeneration(null)
        setState('read-error')
        setError(cause)
      },
    )
  }, [isCurrent])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      cancelTimer()
      inFlightWrite.current = null
      queuedWrites.current = []
      readRequest.current += 1
      writeRequest.current += 1
      context.current = { ...context.current, generation: context.current.generation + 1 }
    }
  }, [cancelTimer])

  useEffect(() => {
    cancelTimer()
    if (context.current.accountId !== accountId) {
      inFlightWrite.current = null
      queuedWrites.current = []
    }
    readRequest.current += 1
    writeRequest.current += 1
    hasLoaded.current = false
    setLoadedContextGeneration(null)
    valueRef.current = ''
    setValue('')
    setError(null)

    const snapshot: NoteContext = {
      accountId,
      signalKey,
      enabled,
      generation: context.current.generation + 1,
    }
    context.current = snapshot

    if (!enabled || !signalKey) {
      setState('idle')
      return () => {
        if (context.current.generation !== snapshot.generation) return
        if (mounted.current && latestAccountId.current === snapshot.accountId) flush()
        else {
          cancelTimer()
          inFlightWrite.current = null
          queuedWrites.current = []
        }
        readRequest.current += 1
        writeRequest.current += 1
        context.current = { ...snapshot, generation: snapshot.generation + 1 }
      }
    }

    load(snapshot)
    return () => {
      if (context.current.generation !== snapshot.generation) return
      if (mounted.current && latestAccountId.current === snapshot.accountId) flush()
      else {
        cancelTimer()
        inFlightWrite.current = null
        queuedWrites.current = []
      }
      readRequest.current += 1
      writeRequest.current += 1
      context.current = { ...snapshot, generation: snapshot.generation + 1 }
    }
  }, [accountId, cancelTimer, enabled, flush, load, signalKey])

  const change = useCallback((nextValue: string) => {
    const snapshot = context.current
    if (
      !snapshot.enabled
      || !snapshot.signalKey
      || !hasLoaded.current
      || snapshot.accountId !== accountId
      || snapshot.signalKey !== signalKey
      || snapshot.enabled !== enabled
    ) return
    cancelTimer()
    // Si une valeur attendait qu'un PUT précédent se termine, cette nouvelle
    // frappe la remplace avant même la fin de sa propre fenêtre de debounce.
    queuedWrites.current = queuedWrites.current.filter(
      (queued) => !sameContext(queued.snapshot, snapshot),
    )
    hasLoaded.current = true
    valueRef.current = nextValue
    setValue(nextValue)
    setState('saving')
    setError(null)
    const requestId = ++writeRequest.current
    const pending = { snapshot, requestId, value: nextValue }
    scheduledWrite.current = pending
    timer.current = setTimeout(() => {
      timer.current = null
      if (scheduledWrite.current === pending) scheduledWrite.current = null
      enqueue(pending)
    }, 500)
  }, [accountId, cancelTimer, enabled, enqueue, signalKey])

  const retry = useCallback(() => {
    const snapshot = context.current
    if (!snapshot.enabled || !snapshot.signalKey) return
    cancelTimer()
    if (!hasLoaded.current) {
      load(snapshot)
      return
    }
    setState('saving')
    setError(null)
    const requestId = ++writeRequest.current
    queuedWrites.current = queuedWrites.current.filter(
      (queued) => !sameContext(queued.snapshot, snapshot),
    )
    enqueue({ snapshot, requestId, value: valueRef.current })
  }, [cancelTimer, enqueue, load])

  const contextMatches = context.current.accountId === accountId
    && context.current.signalKey === signalKey
    && context.current.enabled === enabled
  const waitingForCurrentContext = Boolean(
    enabled
      && signalKey
      && (
        !contextMatches
        || (state !== 'read-error' && loadedContextGeneration !== context.current.generation)
      ),
  )
  const visibleState = waitingForCurrentContext
    ? 'loading'
    : state

  return {
    value: waitingForCurrentContext ? '' : value,
    state: visibleState,
    error: waitingForCurrentContext ? null : error,
    change,
    flush,
    retry,
  }
}
