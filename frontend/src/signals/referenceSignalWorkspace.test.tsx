import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useLayoutEffect } from 'react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../App'
import { useSession } from '../auth/SessionProvider'
import { useSignalNote } from '../reference/dashboard/useSignalNote'
import type { NoteSaveState } from '../reference/dashboard/useSignalNote'
import {
  AUTHENTICATED,
  CATALOGUE,
  DISCOVERY_STATUS,
  ICP,
  LOCKED_ITEM,
  ME,
  UNLOCKED_DETAIL,
  UNLOCKED_ITEM,
  callsTo,
  feedPage,
  mockApi,
  renderApp,
} from '../test/harness'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('workspace Signaux de référence connecté aux données réelles', () => {
  it('utilise la structure exacte et ne demande jamais le détail verrouillé', async () => {
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /billing/plans': { body: CATALOGUE },
    })
    const user = userEvent.setup()

    renderApp(<AppRoutes />, { route: '/app/signals', session: AUTHENTICATED })

    await user.click(await screen.findByRole('button', { name: /accès payant requis/i }))
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}`, 'GET')).toHaveLength(0)
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Abonnement' }),
    ).toBeVisible()
  })

  it('ouvre un signal réel par son paramètre de chemin dans le master/detail exact', async () => {
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, LOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /billing/plans': { body: CATALOGUE },
    })

    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    expect(
      await screen.findByRole('heading', {
        level: 2,
        name: 'Présentation non publiée',
      }),
    ).toBeVisible()
    expect(document.querySelector('.workspace-grid .feed-panel + .detail-panel')).not.toBeNull()
    expect(document.querySelector('.feed-panel')).toHaveAttribute(
      'data-master-detail-pane',
      'list',
    )
    expect(document.querySelector('.detail-panel')).toHaveAttribute(
      'data-master-detail-pane',
      'detail',
    )
  })

  it('enregistre la valeur exacte après 500 ms et annonce honnêtement le résultat', async () => {
    const writes: unknown[] = []
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
      },
      [`PUT /signals/${UNLOCKED_ITEM.signal_id}/note`]: (request) => {
        writes.push(request.body)
        return {
          body: {
            signal_id: UNLOCKED_ITEM.signal_id,
            note: (request.body as { note: string }).note,
            updated_at: '2026-08-29T18:00:00+00:00',
          },
        }
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })
    const textarea = await screen.findByRole('textbox', { name: 'Note sur ce signal' })
    await waitFor(() => {
      expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}/note`, 'GET')).toHaveLength(1)
    })
    await waitFor(() => expect(textarea).toBeEnabled())
    expect(screen.getByText('Aucune note')).toBeVisible()
    vi.useFakeTimers()
    fireEvent.change(textarea, { target: { value: 'Appeler lundi' } })

    expect(screen.getByText('Enregistrement…')).toBeVisible()
    await act(async () => vi.advanceTimersByTimeAsync(499))
    expect(writes).toEqual([])
    await act(async () => vi.advanceTimersByTimeAsync(1))

    expect(writes).toEqual([{ note: 'Appeler lundi' }])
    expect(screen.getByText('Note enregistrée')).toBeVisible()
  })

  it('vide immédiatement le brouillon de note au blur', async () => {
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
      },
      [`PUT /signals/${UNLOCKED_ITEM.signal_id}/note`]: (request) => ({
        body: {
          signal_id: UNLOCKED_ITEM.signal_id,
          note: (request.body as { note: string }).note,
          updated_at: '2026-08-29T18:00:00+00:00',
        },
      }),
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })
    const textarea = await screen.findByRole('textbox', { name: 'Note sur ce signal' })
    await waitFor(() => expect(textarea).toBeEnabled())
    vi.useFakeTimers()

    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'À rappeler demain' } })
      fireEvent.blur(textarea)
      await Promise.resolve()
    })

    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}/note`, 'PUT')).toHaveLength(1)
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}/note`, 'PUT')[0].body).toEqual({
      note: 'À rappeler demain',
    })
  })

  it('réessaie une écriture en échec avec la valeur courante exacte', async () => {
    const writes: string[] = []
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
      },
      [`PUT /signals/${UNLOCKED_ITEM.signal_id}/note`]: (request) => {
        const note = (request.body as { note: string }).note
        writes.push(note)
        return writes.length === 1
          ? { status: 503, body: { detail: { code: 'note_unavailable' } } }
          : {
              body: {
                signal_id: UNLOCKED_ITEM.signal_id,
                note,
                updated_at: '2026-08-29T18:00:00+00:00',
              },
            }
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })
    const textarea = await screen.findByRole('textbox', { name: 'Note sur ce signal' })
    await waitFor(() => expect(textarea).toBeEnabled())
    vi.useFakeTimers()
    fireEvent.change(textarea, { target: { value: 'Relancer jeudi' } })
    await act(async () => vi.advanceTimersByTimeAsync(500))

    const retry = screen.getByRole('button', { name: 'Réessayer' })
    expect(screen.getByRole('alert')).toHaveTextContent('La note n’a pas pu être enregistrée')
    await act(async () => fireEvent.click(retry))

    expect(writes).toEqual(['Relancer jeudi', 'Relancer jeudi'])
    expect(screen.getByText('Note enregistrée')).toBeVisible()
  })

  it('ne permet aucun écrasement tant que la note serveur n’a pas été chargée', async () => {
    let reads = 0
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: () => {
        reads += 1
        return reads === 1
          ? { status: 503, body: { detail: { code: 'note_unavailable' } } }
          : {
              body: {
                signal_id: UNLOCKED_ITEM.signal_id,
                note: 'Note déjà présente sur le serveur',
                updated_at: '2026-08-29T18:00:00+00:00',
              },
            }
      },
      [`PUT /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: { signal_id: UNLOCKED_ITEM.signal_id, note: 'écrasement', updated_at: null },
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })

    const textarea = await screen.findByRole('textbox', { name: 'Note sur ce signal' })
    expect(textarea).toBeDisabled()
    expect(await screen.findByRole('alert')).toHaveTextContent('La note n’a pas pu être chargée')
    fireEvent.change(textarea, { target: { value: 'écrasement' } })
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}/note`, 'PUT')).toHaveLength(0)

    fireEvent.click(screen.getByRole('button', { name: 'Réessayer' }))
    expect(await screen.findByDisplayValue('Note déjà présente sur le serveur')).toBeEnabled()
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}/note`, 'PUT')).toHaveLength(0)
  })

  it('vide le brouillon de l’ancienne sélection et ne lit aucune note verrouillée', async () => {
    const second = {
      ...UNLOCKED_ITEM,
      signal_id: 'sig_unlocked_2',
      company: { ...UNLOCKED_ITEM.company, name: 'Deuxième entreprise réelle' },
      contract: { ...UNLOCKED_ITEM.contract, title: 'Deuxième marché réel' },
    }
    const secondDetail = {
      ...UNLOCKED_DETAIL,
      ...second,
      company_key: 'cmp_second_authorized',
    }
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM, second, LOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${second.signal_id}`]: { body: secondDetail },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
      },
      [`GET /signals/${second.signal_id}/note`]: {
        body: { signal_id: second.signal_id, note: 'Note du second compte', updated_at: null },
      },
      [`PUT /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: { signal_id: UNLOCKED_ITEM.signal_id, note: 'Ne doit pas partir', updated_at: null },
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
      'GET /billing/plans': { body: CATALOGUE },
    })
    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })
    const textarea = await screen.findByRole('textbox', { name: 'Note sur ce signal' })
    await waitFor(() => expect(textarea).toBeEnabled())
    vi.useFakeTimers()
    fireEvent.change(textarea, { target: { value: 'Ne doit pas partir' } })
    fireEvent.click(screen.getByRole('button', { name: /Deuxième entreprise réelle/ }))

    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}/note`, 'PUT')).toHaveLength(1)
    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}/note`, 'PUT')[0].body).toEqual({
      note: 'Ne doit pas partir',
    })
    expect(callsTo(`/signals/${LOCKED_ITEM.signal_id}/note`, 'GET')).toHaveLength(0)
    vi.useRealTimers()
    expect(await screen.findByDisplayValue('Note du second compte')).toBeVisible()
  })

  it('sérialise les PUT pour empêcher une complétion inversée d’écraser la valeur serveur', async () => {
    const resolvers: Array<() => void> = []
    const writes: string[] = []
    let serverNote = ''
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: { signal_id: UNLOCKED_ITEM.signal_id, note: null, updated_at: null },
      },
      [`PUT /signals/${UNLOCKED_ITEM.signal_id}/note`]: (request) => {
        const note = (request.body as { note: string }).note
        writes.push(note)
        return new Promise((resolve) => {
          resolvers.push(() => {
            serverNote = note
            resolve({
              body: {
                signal_id: UNLOCKED_ITEM.signal_id,
                note,
                updated_at: '2026-08-29T18:01:00+00:00',
              },
            })
          })
        })
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(<AppRoutes />, {
      route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
      session: AUTHENTICATED,
    })
    const textarea = await screen.findByRole('textbox', { name: 'Note sur ce signal' })
    await waitFor(() => expect(textarea).toBeEnabled())
    vi.useFakeTimers()
    fireEvent.change(textarea, { target: { value: 'Première' } })
    await act(async () => vi.advanceTimersByTimeAsync(500))
    fireEvent.change(textarea, { target: { value: 'Seconde' } })
    await act(async () => vi.advanceTimersByTimeAsync(500))
    expect(writes).toEqual(['Première'])
    expect(resolvers).toHaveLength(1)

    await act(async () => {
      resolvers[0]()
      await Promise.resolve()
    })
    expect(writes).toEqual(['Première', 'Seconde'])
    expect(serverNote).toBe('Première')

    await act(async () => {
      resolvers[1]()
      await Promise.resolve()
    })
    expect(serverNote).toBe('Seconde')
    expect(textarea).toHaveValue('Seconde')
    expect(screen.getByText('Note enregistrée')).toBeVisible()
  })

  it('annule une note en attente quand le compte connecté change', async () => {
    let noteReads = 0
    mockApi({
      'GET /signals': { body: feedPage([UNLOCKED_ITEM]) },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}`]: { body: UNLOCKED_DETAIL },
      [`GET /signals/${UNLOCKED_ITEM.signal_id}/note`]: () => {
        noteReads += 1
        return {
          body: {
            signal_id: UNLOCKED_ITEM.signal_id,
            note: noteReads === 1 ? 'Compte A' : 'Compte B',
            updated_at: null,
          },
        }
      },
      [`PUT /signals/${UNLOCKED_ITEM.signal_id}/note`]: {
        body: { signal_id: UNLOCKED_ITEM.signal_id, note: 'Compte A modifié', updated_at: null },
      },
      'GET /target-icps': { body: [ICP] },
      'GET /billing/status': { body: DISCOVERY_STATUS },
    })
    renderApp(
      <>
        <AppRoutes />
        <AdoptSecondAccount />
      </>,
      {
        route: `/app/signals/${UNLOCKED_ITEM.signal_id}`,
        session: AUTHENTICATED,
      },
    )
    const textarea = await screen.findByDisplayValue('Compte A')
    vi.useFakeTimers()
    fireEvent.change(textarea, { target: { value: 'Compte A modifié' } })
    fireEvent.click(screen.getByRole('button', { name: 'Basculer sur le compte B' }))
    await act(async () => vi.advanceTimersByTimeAsync(600))

    expect(callsTo(`/signals/${UNLOCKED_ITEM.signal_id}/note`, 'PUT')).toHaveLength(0)
    vi.useRealTimers()
    expect(await screen.findByDisplayValue('Compte B')).toBeVisible()
  })

  it('ne rend jamais la valeur de l’ancienne clé pendant le commit de sélection', async () => {
    const commits: Array<[string, NoteSaveState]> = []
    mockApi({
      'GET /signals/note_a/note': {
        body: { signal_id: 'note_a', note: 'Valeur privée A', updated_at: null },
      },
      'GET /signals/note_b/note': () => new Promise(() => undefined),
    })
    const view = render(
      <NoteHookProbe
        signalKey="note_a"
        onCommit={(value, state) => commits.push([value, state])}
      />,
    )
    expect(commits[0]).toEqual(['', 'loading'])
    await waitFor(() => expect(screen.getByTestId('note-hook')).toHaveTextContent('Valeur privée A|idle'))
    commits.length = 0

    view.rerender(
      <NoteHookProbe
        signalKey="note_b"
        onCommit={(value, state) => commits.push([value, state])}
      />,
    )

    expect(commits[0]).toEqual(['', 'loading'])
  })
})

function AdoptSecondAccount() {
  const { adopt } = useSession()
  return (
    <button
      type="button"
      onClick={() => adopt({ ...ME, account_id: 'acc_2', account_display_name: 'Compte B' })}
    >
      Basculer sur le compte B
    </button>
  )
}

function NoteHookProbe({
  signalKey,
  onCommit,
}: {
  signalKey: string
  onCommit: (value: string, state: NoteSaveState) => void
}) {
  const note = useSignalNote({ accountId: 'acc_note_probe', signalKey, enabled: true })
  useLayoutEffect(() => {
    onCommit(note.value, note.state)
  }, [note.state, note.value, onCommit])
  return <output data-testid="note-hook">{note.value}|{note.state}</output>
}
