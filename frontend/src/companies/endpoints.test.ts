import { afterEach, describe, expect, it, vi } from 'vitest'
import { companies } from '../api/endpoints'
import { mockApi } from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

describe('companies endpoints', () => {
  it('serializes list filters and cursor', async () => {
    mockApi({ 'GET /companies': { body: { items: [], page: {} } } })

    await companies.list({ contact_status: ['to_contact', 'replied'], q: 'bois', limit: 20, cursor: 'next' })

    const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]
    expect(url).toBe('/companies?contact_status=to_contact&contact_status=replied&q=bois&limit=20&cursor=next')
  })

  it('posts contact status and puts notes', async () => {
    mockApi({
      'POST /companies/cmp_0123456789ab/contact': { body: {} },
      'PUT /companies/cmp_0123456789ab/note': { body: {} },
    })

    await companies.contact('cmp_0123456789ab', 'replied')
    await companies.note('cmp_0123456789ab', 'À rappeler mardi')

    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls
    expect(JSON.parse(String(calls[0][1]?.body))).toEqual({ status: 'replied' })
    expect(JSON.parse(String(calls[1][1]?.body))).toEqual({ body: 'À rappeler mardi' })
  })
})
