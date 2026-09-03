import { describe, expect, it, afterEach, vi } from 'vitest'
import { request } from './client'
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
