import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import * as subject from '../useCatalogueRefresh'

beforeEach(() => { vi.useFakeTimers(); vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible') })
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); document.body.innerHTML = '' })

it('refreshes a visible idle catalogue once per minute and stops after unmount', () => {
  const { result, unmount } = renderHook(() => subject.useCatalogueRefresh(true))
  expect(result.current).toBe(0)
  act(() => vi.advanceTimersByTime(60_000))
  expect(result.current).toBe(1)
  unmount()
  expect(vi.getTimerCount()).toBe(0)
})

it('does not refresh while hidden, disabled or the commercial is typing', () => {
  const visibility = vi.spyOn(document, 'visibilityState', 'get')
  visibility.mockReturnValue('hidden')
  const { result, rerender } = renderHook(({ enabled }) => subject.useCatalogueRefresh(enabled), { initialProps: { enabled: true } })
  act(() => vi.advanceTimersByTime(60_000))
  expect(result.current).toBe(0)
  visibility.mockReturnValue('visible')
  const input = document.createElement('input')
  document.body.appendChild(input)
  input.focus()
  act(() => vi.advanceTimersByTime(60_000))
  expect(result.current).toBe(0)
  input.blur()
  rerender({ enabled: false })
  act(() => vi.advanceTimersByTime(60_000))
  expect(result.current).toBe(0)
})
