import { act, fireEvent, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { renderApp } from '../../test/harness'
import { createNoteStore } from '../usePersistedNote'
import { NotesField } from '../components/NotesField'

afterEach(() => vi.useRealTimers())

test('notes field displays literal text, the 2000 limit and acknowledgement only after saving', async () => {
  vi.useFakeTimers()
  let complete: (value: { note: string; revision: number; updated_at: string }) => void = () => undefined
  const store = createNoteStore('account', {
    read: async () => ({ note: null, revision: 0, updated_at: null }),
    save: () => new Promise((resolve) => { complete = resolve }),
  })
  renderApp(<NotesField store={store} identity={{ accountId: 'account', kind: 'signal', entityId: 'signal' }} />)
  await act(async () => { await Promise.resolve() })
  const input = screen.getByRole('textbox', { name: 'Vos notes sur ce signal' })
  expect(input).toHaveAttribute('maxLength', '2000')
  fireEvent.change(input, { target: { value: '<b>Rappeler jeudi</b>' } })
  expect(input).toHaveValue('<b>Rappeler jeudi</b>')
  await act(async () => { await vi.advanceTimersByTimeAsync(600) })
  expect(screen.getByRole('status')).toHaveTextContent('Enregistrement…')
  expect(screen.queryByText('Enregistré')).not.toBeInTheDocument()
  await act(async () => { complete({ note: '<b>Rappeler jeudi</b>', revision: 1, updated_at: '2026-09-13T10:00:00Z' }) })
  expect(screen.getByRole('status')).toHaveTextContent('Enregistré')
  expect(document.querySelector('textarea b')).toBeNull()
  act(() => store.dispose())
})
