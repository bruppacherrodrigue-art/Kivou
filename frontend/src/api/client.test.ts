import { describe, expect, it, afterEach, vi } from 'vitest'
import { onUnauthenticated, request } from './client'
import { mockApi } from '../test/harness'

/* PR2 tâche 1 — la sérialisation des paramètres répétés.
 *
 * Le backend accepte `status` en paramètre répété (`status=a&status=b`), pas
 * en liste séparée par des virgules. `buildUrl` doit donc ajouter un
 * paramètre par élément du tableau, et ignorer les chaînes vides — comme il
 * ignore déjà `null`/`undefined` pour une valeur scalaire.
 */

afterEach(() => vi.unstubAllGlobals())

describe('buildUrl — paramètres de requête', () => {
  it('sérialise une valeur tableau en paramètres répétés', async () => {
    mockApi({ 'GET /signals': { body: {} } })

    await request('/signals', { query: { status: ['new', 'saved'], q: '' } })

    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string
    expect(url).toBe('/signals?status=new&status=saved')
  })

  it('ignore les éléments vides d’un tableau', async () => {
    mockApi({ 'GET /signals': { body: {} } })

    await request('/signals', { query: { status: ['new', '', 'contacted'] } })

    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string
    expect(url).toBe('/signals?status=new&status=contacted')
  })

  it('n’ajoute aucun paramètre pour un tableau vide', async () => {
    mockApi({ 'GET /signals': { body: {} } })

    await request('/signals', { query: { status: [] } })

    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string
    expect(url).toBe('/signals')
  })
})

describe('abort and conditional private writes', () => {
  it('passes the AbortSignal and keeps same-origin cookies', async () => {
    const controller = new AbortController()
    const fetch = mockApi({ 'GET /companies/example': { body: {} } })
    await request('/companies/example', { signal: controller.signal })
    expect(fetch.mock.calls[0][1]).toMatchObject({ signal: controller.signal, credentials: 'same-origin' })
  })

  it('sends If-Match without allowing session or origin header overrides', async () => {
    const fetch = mockApi({ 'DELETE /companies/example/manual-contact': { body: {} } })
    await request('/companies/example/manual-contact', {
      method: 'DELETE', headers: { 'If-Match': '"7"', Host: 'evil.test', Cookie: 'fake', Origin: 'https://evil.test' },
    })
    const headers = new Headers(fetch.mock.calls[0][1]?.headers)
    expect(headers.get('If-Match')).toBe('"7"')
    expect(headers.has('Host')).toBe(false)
    expect(headers.has('Cookie')).toBe(false)
    expect(headers.has('Origin')).toBe(false)
  })

  it('does not replace an intentional abort with a network failure', async () => {
    const controller = new AbortController()
    controller.abort()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('Aborted', 'AbortError')))
    await expect(request('/companies/example', { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('does not broadcast a late unauthorized response from an aborted account request', async () => {
    const controller = new AbortController()
    const listener = vi.fn()
    const unsubscribe = onUnauthenticated(listener)
    vi.stubGlobal('fetch', vi.fn(async () => {
      controller.abort()
      return new Response('{}', { status: 401 })
    }))
    try {
      await expect(request('/companies/old-account', { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' })
      expect(listener).not.toHaveBeenCalled()
    } finally { unsubscribe() }
  })
})
