import { describe, expect, it } from 'vitest'
import { noteKey, prospectingKey, type ProspectingScope } from '../queryKeys'

const scope: ProspectingScope = {
  accountId: 'account-a', targetIcpId: 'profile-a', targetRevision: 3,
  offerCategory: 'materials_and_components', subdivisionCode: 'FR-75',
  minAmount: '500000.01', amountCurrency: 'EUR', accessEpoch: 2,
}

describe('prospecting query identity', () => {
  it('keeps directory resources independent of targeting but isolated by account and access', () => {
    const options = { scopeIndependent: true }
    const key = prospectingKey('directory', scope, { q: 'béton' }, options)
    expect(prospectingKey('directory', { ...scope, targetIcpId: 'other', targetRevision: 9, minAmount: '1' }, { q: 'béton' }, options)).toBe(key)
    expect(prospectingKey('directory', { ...scope, accountId: 'other' }, { q: 'béton' }, options)).not.toBe(key)
    expect(prospectingKey('directory', { ...scope, accessEpoch: 3 }, { q: 'béton' }, options)).not.toBe(key)
  })

  it('separates every field that can change the authorized projection', () => {
    const alternatives: ProspectingScope[] = [
      { ...scope, accountId: 'account-b' }, { ...scope, targetIcpId: 'profile-b' },
      { ...scope, targetRevision: 4 }, { ...scope, offerCategory: null },
      { ...scope, subdivisionCode: null }, { ...scope, minAmount: '500000.02' },
      { ...scope, amountCurrency: 'CHF' }, { ...scope, accessEpoch: 3 },
    ]
    const key = prospectingKey('signals', scope, { q: 'béton', cursor: null })
    for (const alternative of alternatives) {
      expect(prospectingKey('signals', alternative, { q: 'béton', cursor: null })).not.toBe(key)
    }
    expect(prospectingKey('signals', scope, { cursor: 'next', q: 'béton' })).not.toBe(key)
    expect(prospectingKey('signals', scope, { cursor: null, q: 'béton' })).toBe(key)
  })

  it('keeps company private subjects separate and never keys a note by the route alias', () => {
    expect(noteKey({ accountId: 'a', kind: 'company', entityId: 'private-1', addressKey: 'cmp_old' }))
      .toBe(noteKey({ accountId: 'a', kind: 'company', entityId: 'private-1', addressKey: 'cmp_directory_123' }))
    expect(noteKey({ accountId: 'a', kind: 'company', entityId: 'private-1' }))
      .not.toBe(noteKey({ accountId: 'a', kind: 'company', entityId: 'private-2' }))
    expect(noteKey({ accountId: 'a', kind: 'signal', entityId: 'same' }))
      .not.toBe(noteKey({ accountId: 'b', kind: 'signal', entityId: 'same' }))
    expect(noteKey({ accountId: 'a', kind: 'signal', entityId: 'same' }))
      .not.toBe(noteKey({ accountId: 'a', kind: 'company', entityId: 'same' }))
  })
})
