import { expect, test } from 'vitest'
import { formatAmount, durationLabel, safeExternal, signalClock, signalPlace, signalTitle } from '../adapters'
import { UNLOCKED_ITEM } from '../../test/harness'
import type { ProspectingSignal } from '../models'

test('formats exact decimal amounts without a binary floating point conversion', () => {
  expect(formatAmount({ value: '9007199254740993.1234', currency: 'EUR' }, 'fr')).toBe('9\u00a0007\u00a0199\u00a0254\u00a0740\u00a0993,1234\u00a0€')
  expect(formatAmount(null, 'fr')).toBeNull()
})

test('does not invent a start from a duration or rename publication as attribution', () => {
  expect(durationLabel({ value: '18', unit: 'MONTH', scope: 'works', period_kind: 'unspecified', source_path: '/duration' }, 'fr')).toBe('18 mois')
  expect(signalClock({ ...UNLOCKED_ITEM, contract: { ...UNLOCKED_ITEM.contract, dates: { award: null, contract_notification: null, publication: '2026-09-12' } } }, 'fr')).toEqual({ label: 'Publié le', value: '2026-09-12' })
})

test('unsafe source links never become clickable', () => {
  expect(safeExternal('javascript:alert(1)')).toBeNull()
  expect(safeExternal('https://user:pass@example.com')).toBeNull()
  expect(safeExternal('https://example.com/source')).toBe('https://example.com/source')
})

test('falls back through the published client object, lot, contract and headline without truncation', () => {
  expect(signalTitle(UNLOCKED_ITEM)).toBe('Voirie')
  const withoutObject = { ...UNLOCKED_ITEM, factual_display: { ...UNLOCKED_ITEM.factual_display, object_short: null } }
  expect(signalTitle(withoutObject)).toBe(UNLOCKED_ITEM.contract.lot_title)
  const withoutLot = { ...withoutObject, contract: { ...UNLOCKED_ITEM.contract, lot_title: null } }
  expect(signalTitle(withoutLot)).toBe(UNLOCKED_ITEM.contract.title)
  expect(signalTitle({ ...withoutLot, contract: { ...withoutLot.contract, title: null } })).toBe(UNLOCKED_ITEM.factual_display.headline)
})

test('omits missing or invalid money instead of guessing a currency or showing NaN', () => {
  expect(formatAmount({ value: '950000', currency: '' }, 'fr')).toBeNull()
  expect(formatAmount({ value: 'not-a-number', currency: 'EUR' }, 'fr')).toBeNull()
  expect(formatAmount(undefined, 'en')).toBeNull()
})

test('uses readable locality and subdivision names without leaking a subdivision code', () => {
  expect(signalPlace({ ...UNLOCKED_ITEM, contract: { ...UNLOCKED_ITEM.contract, location: { country: 'FR', locality: 'DRAGUIGNAN', subdivision_label: 'VAR', subdivision_code: 'FR-83', postal_code: null } } })).toBe('Draguignan (Var)')
  expect(signalPlace({ ...UNLOCKED_ITEM, contract: { ...UNLOCKED_ITEM.contract, location: { country: 'FR', locality: 'SAINT-ONDRAS', subdivision_label: 'ISÈRE', subdivision_code: 'FR-38', postal_code: null } } })).toBe('Saint-Ondras (Isère)')
  expect(signalPlace({ ...UNLOCKED_ITEM, contract: { ...UNLOCKED_ITEM.contract, location: { country: null, locality: null, subdivision_label: null, subdivision_code: 'FR-83', postal_code: null } } })).toBeNull()
  expect(signalPlace({ ...UNLOCKED_ITEM, contract: { ...UNLOCKED_ITEM.contract, location: null } })).toBeNull()
})

test('keeps each fallback date accurately qualified and omits a missing date', () => {
  expect(signalClock(UNLOCKED_ITEM, 'fr')).toEqual({ label: 'Attribué le', value: '2026-08-04' })
  expect(signalClock({ ...UNLOCKED_ITEM, notice_facts: { publication_date: '2026-09-12' } } as ProspectingSignal, 'fr')).toEqual({ label: 'Attribué le', value: '2026-08-04' })
  expect(signalClock({ ...UNLOCKED_ITEM, contract: { ...UNLOCKED_ITEM.contract, dates: { award: null, contract_notification: '2026-08-06', publication: null } } }, 'fr')).toEqual({ label: 'Notifié le', value: '2026-08-06' })
  expect(signalClock({ ...UNLOCKED_ITEM, contract: { ...UNLOCKED_ITEM.contract, dates: { award: null, contract_notification: null, publication: null } } }, 'fr').value).toBeNull()
})
