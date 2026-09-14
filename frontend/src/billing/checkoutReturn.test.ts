import { afterEach, describe, expect, it, vi } from 'vitest'
import { notifySignOutStarted } from '../api/client'
import { checkoutReturnPath, CHECKOUT_RETURN_TTL_MS, readCheckoutReturn, saveCheckoutReturn, saveCheckoutIntent, validateCheckoutReturn } from './checkoutIntent'

afterEach(() => { sessionStorage.clear(); vi.useRealTimers() })
describe('account-bound checkout return, never an access grant', () => {
  it('preserves the exact signal and artifact without storing signal content', () => {
    saveCheckoutReturn('acc_a', { kind: 'signal', signalKey: 'opaque/key', artifactId: 'artifact 2' })
    const intent = readCheckoutReturn('acc_a')
    expect(intent).toEqual({ kind: 'signal', signalKey: 'opaque/key', artifactId: 'artifact 2' })
    expect(checkoutReturnPath(intent!)).toBe('/app/signals/opaque%2Fkey?presentation_artifact_id=artifact+2')
    expect(readCheckoutReturn('acc_b')).toBeNull()
  })
  it('keeps the addressed company alias, not a guessed canonical key', () => {
    saveCheckoutReturn('acc_a', { kind: 'company', companyKey: 'requested-alias' })
    expect(checkoutReturnPath(readCheckoutReturn('acc_a')!)).toBe('/app/companies/requested-alias')
  })
  it('only retains allowed non-sensitive directory filters on a fixed internal route', () => {
    saveCheckoutReturn('acc_a', { kind: 'directory', search: '?q=béton&department=31&family=construction&sort=city&return=https://evil.test&note=private' })
    expect(checkoutReturnPath(readCheckoutReturn('acc_a')!)).toBe('/app/companies/directory?q=b%C3%A9ton&department=31&family=construction&sort=city')
    expect(JSON.stringify(sessionStorage)).not.toContain('private')
    expect(validateCheckoutReturn({ kind: 'directory', search: 'https://evil.test' })).toBeNull()
    expect(validateCheckoutReturn({ kind: 'company', companyKey: '..' })).toBeNull()
  })
  it('expires without being extended by reads, rejects tampered timestamps and clears on logout intent', () => {
    vi.useFakeTimers(); vi.setSystemTime(1_800_000_000_000)
    saveCheckoutReturn('acc_a', { kind: 'company', companyKey: 'company' })
    vi.advanceTimersByTime(CHECKOUT_RETURN_TTL_MS + 1)
    expect(readCheckoutReturn('acc_a')).toBeNull()
    saveCheckoutReturn('acc_a', { kind: 'company', companyKey: 'company' })
    const key = sessionStorage.key(0)!
    const tampered = JSON.parse(sessionStorage.getItem(key)!)
    sessionStorage.setItem(key, JSON.stringify({ ...tampered, expiresAt: tampered.expiresAt + 1 }))
    expect(readCheckoutReturn('acc_a')).toBeNull()
    saveCheckoutReturn('acc_a', { kind: 'company', companyKey: 'company' })
    notifySignOutStarted()
    expect(readCheckoutReturn('acc_a')).toBeNull()
  })
  it('reads the old signal key once and binds its migration to the current account', () => {
    saveCheckoutIntent('old-key')
    expect(readCheckoutReturn('acc_a')).toEqual({ kind: 'signal', signalKey: 'old-key' })
    expect(readCheckoutReturn('acc_b')).toBeNull()
  })
})
