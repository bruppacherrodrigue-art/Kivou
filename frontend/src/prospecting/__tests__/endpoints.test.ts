import { afterEach, describe, expect, it, vi } from 'vitest'
import { companies, dashboard, signalNotes, signals } from '../../api/endpoints'
import { mockApi, recordedCalls } from '../../test/harness'

afterEach(() => vi.unstubAllGlobals())

describe('prospecting API contracts', () => {
  it('writes reversible status using its workflow revision', async () => {
    mockApi({ 'PUT /signals/signal%2Fone/status': { body: { revision: 4 } } })
    await signals.setStatus('signal/one', 'new', 3)
    expect(recordedCalls[0]).toMatchObject({ method: 'PUT', url: '/signals/signal%2Fone/status', body: { status: 'new', expected_revision: 3 } })
  })

  it('sends CAS revisions for both note types, including blank deletion', async () => {
    mockApi({ 'PUT /signals/s/note': { body: {} }, 'PUT /companies/alias/note': { body: {} } })
    await signalNotes.write('s', '', 4)
    await companies.note('alias', '', 8)
    expect(recordedCalls.map((call) => call.body)).toEqual([{ note: '', expected_revision: 4 }, { body: '', expected_revision: 8 }])
  })

  it('keeps directory search separate and forwards the decimal consultation scope', async () => {
    mockApi({ 'GET /companies/directory': { body: {} }, 'GET /dashboard': { body: {} } })
    await companies.directorySearch({ q: 'Entreprise', department: '31', family: 'travaux', sort: 'name', limit: 20 })
    await dashboard.get({ target_icp_id: 'p', offer_category: 'staffing_and_labour', subdivision_code: 'FR-31', min_amount: '123456789012345678.12', amount_currency: 'EUR' })
    expect(recordedCalls[0].search.get('department')).toBe('31')
    expect(recordedCalls[1].search.get('min_amount')).toBe('123456789012345678.12')
  })

  it('follows idempotently and writes/deletes only the addressed private contact', async () => {
    const fetch = mockApi({
      'PUT /companies/private-alias/prospection': { body: {} },
      'PUT /companies/private-alias/manual-contact': { body: {} },
      'DELETE /companies/private-alias/manual-contact': { body: {} },
    })
    await companies.follow('private-alias')
    await companies.saveManualContact('private-alias', { name: 'Claire', email: 'claire@example.test', expected_revision: 2 })
    await companies.deleteManualContact('private-alias', 3)
    expect(recordedCalls[0].body).toEqual({})
    expect(recordedCalls[1].body).toEqual({ name: 'Claire', email: 'claire@example.test', expected_revision: 2 })
    expect(new Headers(fetch.mock.calls[2][1]?.headers).get('If-Match')).toBe('"3"')
  })
})
