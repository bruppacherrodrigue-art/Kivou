import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createNoteStore, usePersistedNote, type NoteStore, type SavedNote } from '../usePersistedNote'
import type { NoteIdentity } from '../queryKeys'

const identity: NoteIdentity = { accountId: 'a', kind: 'signal', entityId: 'signal-a' }
const saved = (note: string | null, revision: number): SavedNote => ({ note, revision, updated_at: revision ? '2026-09-13T12:00:00Z' : null })
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

const stores: NoteStore[] = []
function setup(initial = saved(null, 0)) {
  const read = vi.fn(async (_identity: NoteIdentity, options: { signal: AbortSignal }) => {
    if (options.signal.aborted) throw new Error('Aborted')
    return initial
  })
  const save = vi.fn(async (_identity: NoteIdentity, input: { note: string; expected_revision: number }, options: { signal: AbortSignal }) => {
    if (options.signal.aborted) throw new Error('Aborted')
    return saved(input.note, input.expected_revision + 1)
  })
  const store = createNoteStore('a', { read, save })
  stores.push(store)
  return { store, read, save }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  for (const store of stores.splice(0)) store.dispose()
  vi.useRealTimers()
})

describe('account-owned persisted note store', () => {
  it('debounces edits for 600 ms and confirms only the acknowledged text', async () => {
    const { store, save } = setup()
    await store.load(identity)
    store.edit(identity, 'Première idée')
    await vi.advanceTimersByTimeAsync(400)
    store.edit(identity, 'Texte définitif')
    await vi.advanceTimersByTimeAsync(599)
    expect(save).not.toHaveBeenCalled()
    expect(store.getSnapshot(identity).status).toBe('dirty')
    await vi.advanceTimersByTimeAsync(1)
    expect(save).toHaveBeenCalledWith(identity, { note: 'Texte définitif', expected_revision: 0 }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(store.getSnapshot(identity)).toMatchObject({ draft: 'Texte définitif', status: 'saved', dirty: false, server: { revision: 1 } })
  })

  it('serializes writes and sends only the newest queued draft with the returned revision', async () => {
    const { store, save } = setup(saved('Initial', 7))
    const first = deferred<SavedNote>()
    save.mockImplementationOnce(() => first.promise)
    await store.load(identity)
    store.edit(identity, 'En vol')
    await vi.advanceTimersByTimeAsync(600)
    store.edit(identity, 'Intermédiaire')
    store.edit(identity, 'Dernière modification')
    await vi.advanceTimersByTimeAsync(600)
    expect(save).toHaveBeenCalledTimes(1)
    expect(store.getSnapshot(identity).status).toBe('saving')
    first.resolve(saved('En vol', 8))
    await vi.advanceTimersByTimeAsync(0)
    expect(save).toHaveBeenCalledTimes(2)
    expect(save.mock.calls[1][1]).toEqual({ note: 'Dernière modification', expected_revision: 8 })
    expect(store.getSnapshot(identity)).toMatchObject({ draft: 'Dernière modification', status: 'saved', server: { revision: 9 } })
  })

  it('does not shorten debounce when a previous request completes during a new edit', async () => {
    const { store, save } = setup()
    const first = deferred<SavedNote>()
    save.mockImplementationOnce(() => first.promise)
    await store.load(identity)
    store.edit(identity, 'A')
    await vi.advanceTimersByTimeAsync(600)
    store.edit(identity, 'B')
    first.resolve(saved('A', 1))
    await vi.advanceTimersByTimeAsync(599)
    expect(save).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(save).toHaveBeenCalledTimes(2)
  })

  it('loads the revision before saving and never overwrites a draft with a late read', async () => {
    const { store, read, save } = setup()
    const pending = deferred<SavedNote>()
    read.mockReturnValueOnce(pending.promise)
    const loading = store.load(identity)
    store.edit(identity, 'Écrit avant le chargement')
    await vi.advanceTimersByTimeAsync(800)
    expect(save).not.toHaveBeenCalled()
    pending.resolve(saved('Ancien texte serveur', 6))
    await loading
    expect(store.getSnapshot(identity).draft).toBe('Écrit avant le chargement')
    await vi.advanceTimersByTimeAsync(0)
    expect(save.mock.calls[0][1]).toEqual({ note: 'Écrit avant le chargement', expected_revision: 6 })
  })

  it('writes a blank tombstone using the previous revision', async () => {
    const { store, save } = setup(saved('À effacer', 2))
    await store.load(identity)
    store.edit(identity, '')
    await vi.advanceTimersByTimeAsync(600)
    expect(save.mock.calls[0][1]).toEqual({ note: '', expected_revision: 2 })
    expect(store.getSnapshot(identity)).toMatchObject({ draft: '', dirty: false, server: { revision: 3, note: '' } })
  })

  it('accepts the server whitespace tombstone without resending the same blank draft forever', async () => {
    const { store, save } = setup(saved('À effacer', 2))
    save.mockResolvedValue(saved(null, 3))
    await store.load(identity)
    store.edit(identity, '   ')
    await vi.advanceTimersByTimeAsync(600)
    expect(store.getSnapshot(identity)).toMatchObject({ draft: '', status: 'saved', dirty: false, server: { revision: 3, note: null } })
    await vi.advanceTimersByTimeAsync(600)
    expect(save).toHaveBeenCalledTimes(1)
  })

  it('does not write an unchanged note or a draft restored before debounce', async () => {
    const { store, save } = setup(saved('Initial', 1))
    await store.load(identity)
    store.edit(identity, 'Temporaire')
    store.edit(identity, 'Initial')
    await vi.advanceTimersByTimeAsync(1000)
    expect(save).not.toHaveBeenCalled()
    expect(store.hasUnsavedChanges()).toBe(false)
  })

  it.each([0, 401, 403, 404, 500])('keeps draft after error %s and retries without announcing success', async (status) => {
    const { store, save } = setup(saved('Ancien', 1))
    save.mockRejectedValueOnce({ status })
    await store.load(identity)
    store.edit(identity, 'À garder')
    await vi.advanceTimersByTimeAsync(600)
    expect(store.getSnapshot(identity)).toMatchObject({ draft: 'À garder', status: 'error', dirty: true, server: { note: 'Ancien', revision: 1 } })
    await vi.advanceTimersByTimeAsync(5000)
    expect(save).toHaveBeenCalledTimes(1)
    await store.retry(identity)
    expect(store.getSnapshot(identity)).toMatchObject({ status: 'saved', dirty: false, server: { note: 'À garder' } })
  })

  it('retries a failed initial read without losing text typed before the failure', async () => {
    const { store, read, save } = setup(saved('Serveur', 4))
    read.mockRejectedValueOnce({ status: 503 })
    await store.load(identity)
    store.edit(identity, 'Brouillon')
    await store.retry(identity)
    await vi.advanceTimersByTimeAsync(600)
    expect(save.mock.calls[0][1]).toEqual({ note: 'Brouillon', expected_revision: 4 })
  })

  it('keeps both versions on conflict until the user explicitly accepts the server', async () => {
    const { store, save } = setup(saved('Initial', 2))
    save.mockRejectedValueOnce({ status: 409, current: saved('Autre onglet', 3) })
    await store.load(identity)
    store.edit(identity, 'Mon brouillon')
    await vi.advanceTimersByTimeAsync(600)
    expect(store.getSnapshot(identity)).toMatchObject({ status: 'conflict', draft: 'Mon brouillon', conflict: { note: 'Autre onglet', revision: 3 } })
    store.edit(identity, 'Mon brouillon complété')
    await vi.advanceTimersByTimeAsync(1000)
    await store.retry(identity)
    expect(save).toHaveBeenCalledTimes(1)
    store.acceptServer(identity)
    expect(store.getSnapshot(identity)).toMatchObject({ draft: 'Autre onglet', dirty: false, conflict: null, server: { revision: 3 } })
  })

  it('overwrites only after explicit conflict resolution using the latest server revision', async () => {
    const { store, save } = setup(saved('Initial', 2))
    save.mockRejectedValueOnce({ status: 409, current: saved('Autre onglet', 8) })
    await store.load(identity)
    store.edit(identity, 'Ma version')
    await vi.advanceTimersByTimeAsync(600)
    await store.overwriteDraft(identity)
    expect(save.mock.calls[1][1]).toEqual({ note: 'Ma version', expected_revision: 8 })
    expect(store.getSnapshot(identity)).toMatchObject({ status: 'saved', server: { revision: 9 } })
  })

  it('reads the current server version when a 409 omits the conflict body', async () => {
    const { store, read, save } = setup(saved('Initial', 2))
    save.mockRejectedValueOnce({ status: 409 })
    await store.load(identity)
    read.mockResolvedValueOnce(saved('Plus récente', 12))
    store.edit(identity, 'Ma version')
    await vi.advanceTimersByTimeAsync(600)
    expect(store.getSnapshot(identity)).toMatchObject({ status: 'conflict', draft: 'Ma version', conflict: { revision: 12 } })
    expect(save).toHaveBeenCalledTimes(1)
  })

  it('shares the same private subject across aliases but writes through the original authorized alias', async () => {
    const { store, save } = setup()
    const first = { accountId: 'a', kind: 'company' as const, entityId: 'private-a', addressKey: 'cmp_original' }
    const alias = { ...first, addressKey: 'cmp_directory_123456789' }
    const isolated = { ...alias, entityId: 'private-b' }
    await store.load(first)
    store.edit(first, 'Note privée A')
    expect(store.getSnapshot(alias).draft).toBe('Note privée A')
    expect(store.getSnapshot(isolated).draft).toBe('')
    await vi.advanceTimersByTimeAsync(600)
    expect(save.mock.calls[0][0]).toEqual(first)
    expect(() => store.getSnapshot({ ...first, accountId: 'b' })).toThrow(/account/i)
  })

  it('prevents unload while a draft or request is pending and releases the guard after success', async () => {
    const { store } = setup()
    await store.load(identity)
    store.edit(identity, 'Non confirmé')
    const unsaved = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unsaved)
    expect(unsaved.defaultPrevented).toBe(true)
    await vi.advanceTimersByTimeAsync(600)
    const complete = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(complete)
    expect(complete.defaultPrevented).toBe(false)
  })

  it('aborts pending requests and removes all private state on disposal, ignoring a late result', async () => {
    const { store, save } = setup()
    const pending = deferred<SavedNote>()
    save.mockImplementationOnce(() => pending.promise)
    await store.load(identity)
    store.edit(identity, 'Privé')
    await vi.advanceTimersByTimeAsync(600)
    const requestSignal = save.mock.calls[0][2].signal
    store.edit(identity, 'Ne pas envoyer après logout')
    store.dispose()
    expect(requestSignal.aborted).toBe(true)
    pending.resolve(saved('Privé', 1))
    await vi.advanceTimersByTimeAsync(1000)
    expect(save).toHaveBeenCalledTimes(1)
    expect(store.getSnapshot(identity)).toMatchObject({ draft: '', server: null, dirty: false })
    expect(store.hasUnsavedChanges()).toBe(false)
  })

  it('aborts an old account read without leaking its result into a new account store', async () => {
    const { store, read } = setup()
    const pending = deferred<SavedNote>()
    read.mockReturnValueOnce(pending.promise)
    const loading = store.load(identity)
    await vi.advanceTimersByTimeAsync(0)
    const requestSignal = read.mock.calls[0][1].signal
    store.dispose()
    const next = createNoteStore('b', { read: async () => saved('Compte B', 1), save: async () => saved('Compte B', 2) })
    stores.push(next)
    const nextIdentity = { ...identity, accountId: 'b' }
    await next.load(nextIdentity)
    pending.resolve(saved('Donnée privée A', 8))
    await loading
    expect(requestSignal.aborted).toBe(true)
    expect(store.getSnapshot(identity).draft).toBe('')
    expect(next.getSnapshot(nextIdentity).draft).toBe('Compte B')
  })

  it('keeps draft and pending save when its React editor closes then reopens', async () => {
    const { store, save } = setup()
    const editor = renderHook(() => usePersistedNote(store, identity))
    await act(async () => { await store.load(identity) })
    act(() => editor.result.current.setDraft('<script>texte littéral</script>'))
    editor.unmount()
    await act(async () => { await vi.advanceTimersByTimeAsync(300) })
    const reopened = renderHook(() => usePersistedNote(store, identity))
    expect(reopened.result.current.draft).toBe('<script>texte littéral</script>')
    await act(async () => { await vi.advanceTimersByTimeAsync(300) })
    expect(save).toHaveBeenCalledTimes(1)
    expect(reopened.result.current.status).toBe('saved')
    reopened.unmount()
  })
})
