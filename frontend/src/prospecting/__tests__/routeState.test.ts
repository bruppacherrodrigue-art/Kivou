import { beforeEach, describe, expect, it } from 'vitest'
import {
  clearAccountConsultationPreferences, clearConsultationPreference, clearConsultationSearch,
  resolveConsultationState, safeInternalReturn, saveConsultationPreference,
  signalDetailPath, writeConsultationSearch, type ConsultationPolicy,
} from '../routeState'

const policies: ConsultationPolicy[] = [
  { targetIcpId: 'profile-a', offers: ['materials_and_components', 'equipment_rental'],
    subdivisions: ['FR-75', 'FR-69'], currencies: ['EUR', 'CHF'],
    defaultMinAmount: '500000', defaultAmountCurrency: 'EUR' },
  { targetIcpId: 'profile-b', offers: ['equipment_rental'], subdivisions: ['CH-GE'],
    currencies: ['CHF'], defaultMinAmount: '0', defaultAmountCurrency: 'CHF' },
]
const options = { accountId: 'account-a', policies, defaultTargetIcpId: 'profile-a' }
const saved = {
  targetIcpId: 'profile-a', offerCategory: 'equipment_rental', subdivisionCode: 'FR-69',
  minAmount: '1000000.0001', amountCurrency: 'EUR',
}

beforeEach(() => sessionStorage.clear())

describe('global consultation routing', () => {
  it('uses URL first, then account/profile preferences, then profile defaults', () => {
    saveConsultationPreference('account-a', saved)
    const { selection } = resolveConsultationState('?offer_category=materials_and_components', options)
    expect(selection).toEqual({ ...saved, offerCategory: 'materials_and_components' })
    expect(resolveConsultationState('', { ...options, accountId: 'account-b' }).selection)
      .toEqual({ targetIcpId: 'profile-a', offerCategory: null, subdivisionCode: null,
        minAmount: '500000', amountCurrency: 'EUR' })
  })

  it('restores the selected profile, but never reads another profile preference', () => {
    const second = { targetIcpId: 'profile-b', offerCategory: 'equipment_rental', subdivisionCode: 'CH-GE', minAmount: '42.01', amountCurrency: 'CHF' }
    saveConsultationPreference('account-a', saved)
    saveConsultationPreference('account-a', second)
    expect(resolveConsultationState('', options).selection).toEqual(second)
    expect(resolveConsultationState('?target_icp_id=profile-a', options).selection).toEqual(saved)
  })

  it('revalidates untrusted or revoked options without applying invalid values', () => {
    saveConsultationPreference('account-a', saved)
    const result = resolveConsultationState('?target_icp_id=foreign&offer_category=staffing&subdivision_code=FR-00&min_amount=1e9&amount_currency=USD', options)
    expect(result.selection).toEqual({ targetIcpId: 'profile-a', offerCategory: null,
      subdivisionCode: null, minAmount: '500000', amountCurrency: 'EUR' })
    expect(result.invalidParameters.sort()).toEqual(['amount_currency', 'min_amount', 'offer_category', 'subdivision_code', 'target_icp_id'])
    const revised = [{ ...policies[0], offers: ['materials_and_components'] }]
    expect(resolveConsultationState('', { ...options, policies: revised }).selection?.offerCategory).toBeNull()
  })

  it('preserves exact decimal strings without converting money through Number', () => {
    const value = '999999999999999999999999.123456789'
    expect(resolveConsultationState(`?min_amount=${value}`, options).selection?.minAmount).toBe(value)
    expect(resolveConsultationState('?min_amount=-1', options).invalidParameters).toContain('min_amount')
    expect(resolveConsultationState('?min_amount=0', options).invalidParameters).toContain('min_amount')
    expect(resolveConsultationState('?min_amount=1000000&amount_currency=CHF', options).selection?.amountCurrency).toBe('CHF')
  })

  it('never reinterprets the profile amount in a different currency without an explicit valid amount', () => {
    for (const search of ['?amount_currency=CHF', '?amount_currency=CHF&min_amount=invalid']) {
      expect(resolveConsultationState(search, options).selection).toMatchObject({ minAmount: '500000', amountCurrency: 'EUR' })
    }
  })

  it('does not reinterpret a stored amount when only a different URL currency is supplied', () => {
    saveConsultationPreference('account-a', saved)
    expect(resolveConsultationState('?amount_currency=CHF', options).selection).toMatchObject({ minAmount: '500000', amountCurrency: 'EUR' })
  })

  it('requires an explicit currency when a profile has no monetary threshold', () => {
    const noThreshold = { ...options, policies: [{ ...policies[0], defaultMinAmount: null, defaultAmountCurrency: null }] }
    expect(resolveConsultationState('?min_amount=1000', noThreshold).selection).toMatchObject({ minAmount: null, amountCurrency: null })
    expect(resolveConsultationState('?min_amount=1000&amount_currency=EUR', noThreshold).selection).toMatchObject({ minAmount: '1000', amountCurrency: 'EUR' })
  })

  it('keeps list filters and signal artifact while propagating the global selection', () => {
    const artifact = 'a'.repeat(64)
    const search = writeConsultationSearch(`?status=saved&q=béton&presentation_artifact_id=${artifact}`, saved)
    for (const path of ['/app/dashboard', '/app/signals', '/app/companies']) {
      expect(resolveConsultationState(new URL(path + search, 'https://kivou.invalid').search, options).selection).toEqual(saved)
    }
    expect(new URLSearchParams(search).get('status')).toBe('saved')
    expect(new URLSearchParams(search).get('presentation_artifact_id')).toBe(artifact)
    expect(signalDetailPath('notice/lot', search)).toBe(`/app/signals/notice%2Flot${search}`)
  })

  it('resets overrides without clearing list filters, other accounts, or changing the stored profile', () => {
    saveConsultationPreference('account-a', saved)
    saveConsultationPreference('account-b', saved)
    clearConsultationPreference('account-a', 'profile-a')
    const defaults = resolveConsultationState('?target_icp_id=profile-a', options).selection!
    expect(defaults.minAmount).toBe('500000')
    expect(defaults.offerCategory).toBeNull()
    const reset = new URLSearchParams(clearConsultationSearch(writeConsultationSearch('?q=béton&status=saved', saved)))
    expect([...reset.entries()]).toEqual([['q', 'béton'], ['status', 'saved'], ['target_icp_id', 'profile-a']])
    clearAccountConsultationPreferences('account-a')
    expect(resolveConsultationState('', { ...options, accountId: 'account-b' }).selection).toEqual(saved)
  })

  it('degrades to validated URL/defaults if session storage is unavailable', () => {
    const unavailable = { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') }, removeItem: () => { throw new Error('blocked') }, key: () => null, length: 0 }
    expect(saveConsultationPreference('account-a', saved, unavailable)).toBe(false)
    expect(resolveConsultationState('?subdivision_code=FR-75', { ...options, storage: unavailable }).selection?.subdivisionCode).toBe('FR-75')
    expect(() => clearAccountConsultationPreferences('account-a', unavailable)).not.toThrow()
    expect(resolveConsultationState('', { ...options, policies: [] }).selection).toBeNull()
  })

  it.each(['https://evil.invalid/app/companies/x', '//evil.invalid', '/login', '/app/../login', '/app/%2e%2e/login', '/app/\\evil.invalid', '/app/%5cevil.invalid', '/app/companies/x\n'])('rejects unsafe internal return %s', (value) => {
    expect(safeInternalReturn(value)).toBeNull()
  })

  it('retains only internal return paths and valid artifact identifiers', () => {
    expect(safeInternalReturn('/app/companies/directory/123456789?view=directory')).toBe('/app/companies/directory/123456789?view=directory')
    expect(signalDetailPath('signal-a', '?presentation_artifact_id=invalid&status=saved')).toBe('/app/signals/signal-a?status=saved')
  })
})
