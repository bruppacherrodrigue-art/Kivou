import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react'
import { noteKey, type NoteIdentity } from './queryKeys'

export interface SavedNote {
  note: string | null
  revision: number
  updated_at: string | null
}

export interface NoteTransport {
  read: (identity: NoteIdentity, options: { signal: AbortSignal }) => Promise<SavedNote>
  save: (identity: NoteIdentity, input: { note: string; expected_revision: number }, options: { signal: AbortSignal }) => Promise<SavedNote>
  /** Adapts the backend's conflict envelope. A missing record triggers a fresh read. */
  conflict?: (error: unknown) => SavedNote | null
}

export interface NoteState {
  draft: string
  server: SavedNote | null
  dirty: boolean
  status: 'loading' | 'idle' | 'dirty' | 'saving' | 'saved' | 'error' | 'conflict'
  conflict: SavedNote | null
  error: unknown | null
}

export interface NoteStore {
  getSnapshot: (identity: NoteIdentity) => NoteState
  subscribe: (identity: NoteIdentity, listener: () => void) => () => void
  load: (identity: NoteIdentity) => Promise<void>
  edit: (identity: NoteIdentity, draft: string) => void
  retry: (identity: NoteIdentity) => Promise<void>
  acceptServer: (identity: NoteIdentity) => void
  overwriteDraft: (identity: NoteIdentity) => Promise<void>
  hasUnsavedChanges: () => boolean
  /** The account/session owner calls this, never a closing editor. */
  dispose: () => void
}

const EMPTY: NoteState = { draft: '', server: null, dirty: false, status: 'idle', conflict: null, error: null }
const DEBOUNCE_MS = 600

interface Entry {
  identity: NoteIdentity
  state: NoteState
  listeners: Set<() => void>
  loaded: boolean
  edited: boolean
  editedAt: number
  timer: ReturnType<typeof setTimeout> | null
  readPromise: Promise<void> | null
  writePromise: Promise<void> | null
  readController: AbortController | null
  writeController: AbortController | null
}

function errorRecord(error: unknown): Record<string, unknown> {
  return typeof error === 'object' && error !== null ? error as Record<string, unknown> : {}
}

function savedNote(value: unknown): SavedNote | null {
  const item = errorRecord(value)
  return (item.note === null || typeof item.note === 'string')
    && typeof item.revision === 'number' && Number.isSafeInteger(item.revision) && item.revision >= 0
    && (item.updated_at === null || typeof item.updated_at === 'string')
    ? { note: item.note, revision: item.revision, updated_at: item.updated_at } as SavedNote : null
}

function defaultConflict(error: unknown): SavedNote | null {
  const envelope = errorRecord(error)
  return savedNote(envelope.current) ?? savedNote(errorRecord(envelope.extra).current)
}

export function createNoteStore(accountId: string, transport: NoteTransport): NoteStore {
  const entries = new Map<string, Entry>()
  let disposed = false
  let unloadGuard = false

  const hasUnsavedChanges = () => !disposed && [...entries.values()].some((entry) =>
    entry.state.dirty || entry.state.status === 'saving' || entry.state.status === 'conflict',
  )
  const beforeUnload = (event: BeforeUnloadEvent) => {
    if (!hasUnsavedChanges()) return
    event.preventDefault()
    event.returnValue = ''
  }
  const synchronizeUnloadGuard = () => {
    if (typeof window === 'undefined') return
    const needed = hasUnsavedChanges()
    if (needed === unloadGuard) return
    unloadGuard = needed
    if (needed) window.addEventListener('beforeunload', beforeUnload)
    else window.removeEventListener('beforeunload', beforeUnload)
  }
  const entryFor = (identity: NoteIdentity): Entry => {
    if (identity.accountId !== accountId) throw new Error('Note store account mismatch')
    const key = noteKey(identity)
    const existing = entries.get(key)
    if (existing) return existing
    const entry: Entry = {
      identity: { ...identity }, state: { ...EMPTY, status: 'loading' }, listeners: new Set(),
      loaded: false, edited: false, editedAt: 0, timer: null,
      readPromise: null, writePromise: null, readController: null, writeController: null,
    }
    if (!disposed) entries.set(key, entry)
    return entry
  }
  const publish = (entry: Entry, patch: Partial<NoteState>) => {
    if (disposed) return
    const state = { ...entry.state, ...patch }
    state.dirty = (!entry.loaded && entry.edited) || state.draft !== (state.server?.note ?? '')
    entry.state = state
    synchronizeUnloadGuard()
    for (const listener of entry.listeners) listener()
  }
  const cancelTimer = (entry: Entry) => {
    if (entry.timer !== null) clearTimeout(entry.timer)
    entry.timer = null
  }
  const schedule = (entry: Entry) => {
    cancelTimer(entry)
    if (disposed || !entry.loaded || entry.writePromise || !entry.state.dirty
      || entry.state.status === 'conflict' || entry.state.status === 'error') return
    entry.timer = setTimeout(() => {
      entry.timer = null
      void write(entry)
    }, Math.max(0, DEBOUNCE_MS - (Date.now() - entry.editedAt)))
  }
  const readConflict = async (entry: Entry, error: unknown, controller: AbortController) => {
    try {
      const current = transport.conflict?.(error) ?? defaultConflict(error)
        ?? await transport.read(entry.identity, { signal: controller.signal })
      if (!disposed && !controller.signal.aborted) {
        const validated = savedNote(current)
        if (!validated) throw new Error('Invalid conflict note response')
        publish(entry, { status: 'conflict', conflict: validated, error })
      }
    } catch (readError) {
      if (!disposed && !controller.signal.aborted) publish(entry, { status: 'conflict', conflict: null, error: readError })
    }
  }
  function write(entry: Entry): Promise<void> {
    if (disposed || !entry.loaded || !entry.state.dirty || entry.state.status === 'conflict') return Promise.resolve()
    if (entry.writePromise) return entry.writePromise
    cancelTimer(entry)
    const controller = new AbortController()
    entry.writeController = controller
    const input = { note: entry.state.draft, expected_revision: entry.state.server!.revision }
    publish(entry, { status: 'saving', error: null, conflict: null })
    const promise = Promise.resolve().then(async () => {
      if (disposed || controller.signal.aborted) return
      try {
        const response = await transport.save(entry.identity, input, { signal: controller.signal })
        if (disposed || controller.signal.aborted) return
        const committed = savedNote(response)
        if (!committed || committed.revision <= input.expected_revision) throw new Error('Invalid saved note revision')
        // The API normalizes an all-whitespace deletion to a blank tombstone.
        // Adopt its acknowledged value only if no newer draft has been typed.
        const draft = entry.state.draft === input.note ? committed.note ?? '' : entry.state.draft
        publish(entry, {
          server: committed, draft, error: null,
          status: draft === (committed.note ?? '') ? 'saved' : 'dirty',
        })
      } catch (error) {
        if (disposed || controller.signal.aborted) return
        if (errorRecord(error).status === 409) {
          publish(entry, { status: 'conflict', conflict: null, error })
          await readConflict(entry, error, controller)
        } else publish(entry, { status: 'error', error })
      } finally {
        entry.writePromise = null
        entry.writeController = null
        if (!disposed) schedule(entry)
      }
    })
    entry.writePromise = promise
    return promise
  }
  const load = (identity: NoteIdentity): Promise<void> => {
    if (disposed) return Promise.resolve()
    const entry = entryFor(identity)
    if (entry.loaded) return Promise.resolve()
    if (entry.readPromise) return entry.readPromise
    const controller = new AbortController()
    entry.readController = controller
    publish(entry, { status: 'loading', error: null })
    const promise = Promise.resolve().then(async () => {
      if (disposed || controller.signal.aborted) return
      try {
        const response = await transport.read(entry.identity, { signal: controller.signal })
        if (disposed || controller.signal.aborted) return
        const current = savedNote(response)
        if (!current) throw new Error('Invalid note response')
        entry.loaded = true
        const draft = entry.edited ? entry.state.draft : current.note ?? ''
        publish(entry, { server: current, draft, status: draft === (current.note ?? '') ? 'idle' : 'dirty' })
        schedule(entry)
      } catch (error) {
        if (!disposed && !controller.signal.aborted) publish(entry, { status: 'error', error })
      } finally {
        entry.readPromise = null
        entry.readController = null
      }
    })
    entry.readPromise = promise
    return promise
  }
  return {
    getSnapshot: (identity) => {
      if (identity.accountId !== accountId) throw new Error('Note store account mismatch')
      return disposed ? EMPTY : entryFor(identity).state
    },
    subscribe: (identity, listener) => {
      if (disposed) return () => undefined
      const entry = entryFor(identity)
      entry.listeners.add(listener)
      return () => { entry.listeners.delete(listener) }
    },
    load,
    edit: (identity, draft) => {
      if (disposed) return
      const entry = entryFor(identity)
      entry.edited = true
      entry.editedAt = Date.now()
      const unresolvedConflict = entry.state.status === 'conflict'
      publish(entry, {
        draft,
        status: unresolvedConflict ? 'conflict' : entry.writePromise ? 'saving' : 'dirty',
        error: unresolvedConflict ? entry.state.error : null,
      })
      if (entry.loaded) {
        if (!entry.state.dirty && !entry.writePromise && !unresolvedConflict) publish(entry, { status: 'idle' })
        schedule(entry)
      }
    },
    retry: async (identity) => {
      if (disposed) return
      const entry = entryFor(identity)
      if (entry.state.status === 'conflict') {
        if (!entry.state.conflict && !entry.writePromise) {
          const controller = new AbortController()
          entry.writeController = controller
          const promise = readConflict(entry, entry.state.error, controller)
          entry.writePromise = promise
          await promise
          entry.writePromise = null
          entry.writeController = null
        }
        return
      }
      if (!entry.loaded) await load(identity)
      if (entry.loaded) await write(entry)
    },
    acceptServer: (identity) => {
      if (disposed) return
      const entry = entryFor(identity)
      const current = entry.state.conflict
      if (!current || entry.writePromise) return
      cancelTimer(entry)
      publish(entry, { server: current, draft: current.note ?? '', conflict: null, error: null, status: 'idle' })
    },
    overwriteDraft: async (identity) => {
      if (disposed) return
      const entry = entryFor(identity)
      const current = entry.state.conflict
      if (!current || entry.writePromise) return
      publish(entry, { server: current, conflict: null, error: null, status: 'dirty' })
      if (entry.state.dirty) await write(entry)
      else publish(entry, { status: 'idle' })
    },
    hasUnsavedChanges,
    dispose: () => {
      if (disposed) return
      disposed = true
      for (const entry of entries.values()) {
        cancelTimer(entry)
        entry.readController?.abort()
        entry.writeController?.abort()
        entry.state = EMPTY
        for (const listener of entry.listeners) listener()
        entry.listeners.clear()
      }
      entries.clear()
      synchronizeUnloadGuard()
    },
  }
}

export function usePersistedNote(store: NoteStore, identity: NoteIdentity) {
  const { accountId, kind, entityId, addressKey } = identity
  const stableIdentity = useMemo(() => ({ accountId, kind, entityId, addressKey }), [accountId, kind, entityId, addressKey])
  const subscribe = useCallback((listener: () => void) => store.subscribe(stableIdentity, listener), [store, stableIdentity])
  const snapshot = useCallback(() => store.getSnapshot(stableIdentity), [store, stableIdentity])
  const state = useSyncExternalStore(subscribe, snapshot, snapshot)
  useEffect(() => { void store.load(stableIdentity) }, [store, stableIdentity])
  return useMemo(() => ({
    ...state,
    key: noteKey(stableIdentity),
    setDraft: (draft: string) => store.edit(stableIdentity, draft),
    retry: () => store.retry(stableIdentity),
    acceptServer: () => store.acceptServer(stableIdentity),
    overwriteDraft: () => store.overwriteDraft(stableIdentity),
  }), [state, store, stableIdentity])
}
