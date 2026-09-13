export interface ConsultationState {
  targetIcpId: string
  offerCategory: string | null
  subdivisionCode: string | null
  minAmount: string | null
  amountCurrency: string | null
}

/** Options are supplied by the current authorized profile, never inferred from a plan name. */
export interface ConsultationPolicy {
  targetIcpId: string
  offers: readonly string[]
  subdivisions: readonly string[]
  currencies: readonly string[]
  defaultMinAmount: string | null
  defaultAmountCurrency: string | null
  /** False when the server's filter entitlement only permits choosing a profile. */
  allowRefinement?: boolean
}

type PreferenceStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem' | 'key' | 'length'>
const PREFIX = 'kivou.prospecting.consultation.v1:'
const storageKey = (accountId: string, profileId?: string) => PREFIX + JSON.stringify(
  profileId === undefined ? [accountId] : [accountId, profileId],
)
const fields = {
  targetIcpId: 'target_icp_id', offerCategory: 'offer_category', subdivisionCode: 'subdivision_code',
  minAmount: 'min_amount', amountCurrency: 'amount_currency',
} as const

function sessionStorageOrNull(): PreferenceStorage | null {
  try { return typeof window === 'undefined' ? null : window.sessionStorage } catch { return null }
}

function storedValue(storage: PreferenceStorage | null, key: string): unknown {
  try {
    const value = storage?.getItem(key)
    return value ? JSON.parse(value) as unknown : null
  } catch { return null }
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {}
}

function decimal(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 80 || !/^\d+(?:\.\d+)?$/.test(value)) return null
  const [integer, fraction = ''] = value.split('.')
  const whole = integer.replace(/^0+(?=\d)/, '')
  const remainder = fraction.replace(/0+$/, '')
  return remainder ? `${whole}.${remainder}` : whole
}

function below(value: string, minimum: string): boolean {
  const [integer, fraction = ''] = value.split('.')
  const [minInteger, minFraction = ''] = minimum.split('.')
  if (integer.length !== minInteger.length) return integer.length < minInteger.length
  if (integer !== minInteger) return integer < minInteger
  const places = Math.max(fraction.length, minFraction.length)
  return fraction.padEnd(places, '0') < minFraction.padEnd(places, '0')
}

export function resolveConsultationState(search: string, options: {
  accountId: string
  policies: readonly ConsultationPolicy[]
  defaultTargetIcpId?: string
  storage?: PreferenceStorage | null
}): { selection: ConsultationState | null; invalidParameters: string[] } {
  const { accountId, policies } = options
  const storage = options.storage === undefined ? sessionStorageOrNull() : options.storage
  const params = new URLSearchParams(search)
  const invalidParameters: string[] = []
  const fallback = policies.find((policy) => policy.targetIcpId === options.defaultTargetIcpId) ?? policies[0]
  if (!fallback) return { selection: null, invalidParameters }
  const requestedProfile = params.has(fields.targetIcpId)
    ? params.get(fields.targetIcpId) : storedValue(storage, storageKey(accountId))
  let policy = policies.find((candidate) => candidate.targetIcpId === requestedProfile)
  if (!policy) {
    if (requestedProfile !== null && requestedProfile !== undefined) invalidParameters.push(fields.targetIcpId)
    policy = fallback
  }
  const stored = record(storedValue(storage, storageKey(accountId, policy.targetIcpId)))
  const choose = (field: keyof ConsultationState): unknown => params.has(fields[field])
    ? params.get(fields[field]) : stored[field]
  if (policy.allowRefinement === false) {
    for (const field of ['offerCategory', 'subdivisionCode', 'minAmount', 'amountCurrency'] as const) {
      const value = choose(field)
      if (value !== undefined && value !== null && value !== '') invalidParameters.push(fields[field])
    }
    return { selection: { targetIcpId: policy.targetIcpId, offerCategory: null, subdivisionCode: null, minAmount: null, amountCurrency: null }, invalidParameters }
  }
  const option = (field: 'offerCategory' | 'subdivisionCode' | 'amountCurrency', allowed: readonly string[], defaultValue: string | null): string | null => {
    const value = choose(field)
    if (value === undefined || value === null || value === '') return defaultValue
    if (typeof value === 'string' && allowed.includes(value)) return value
    invalidParameters.push(fields[field])
    return defaultValue
  }
  let amountCurrency = option('amountCurrency', policy.currencies, policy.defaultAmountCurrency)
  let minInput = choose('minAmount')
  if (params.has(fields.amountCurrency) && !params.has(fields.minAmount)
    && stored.amountCurrency !== undefined && amountCurrency !== stored.amountCurrency) minInput = undefined
  const defaultMin = decimal(policy.defaultMinAmount)
  let minAmount = defaultMin
  if (minInput !== undefined && minInput !== null && minInput !== '') {
    const normalized = decimal(minInput)
    if (normalized === null || (amountCurrency === policy.defaultAmountCurrency && defaultMin !== null && below(normalized, defaultMin))) {
      invalidParameters.push(fields.minAmount)
    } else minAmount = normalized
  }
  // A missing/invalid amount cannot change the denomination of a profile threshold.
  if (amountCurrency !== policy.defaultAmountCurrency && decimal(minInput) === null) {
    amountCurrency = policy.defaultAmountCurrency
    if (!invalidParameters.includes(fields.amountCurrency)) invalidParameters.push(fields.amountCurrency)
  }
  if (minAmount !== null && amountCurrency === null) {
    minAmount = defaultMin
    if (!invalidParameters.includes(fields.amountCurrency)) invalidParameters.push(fields.amountCurrency)
  }
  return {
    selection: {
      targetIcpId: policy.targetIcpId,
      offerCategory: option('offerCategory', policy.offers, null),
      subdivisionCode: option('subdivisionCode', policy.subdivisions, null),
      minAmount, amountCurrency,
    },
    invalidParameters,
  }
}

/** Only the five approved preference fields are written; callers revalidate on every read. */
export function saveConsultationPreference(accountId: string, selection: ConsultationState, storage: PreferenceStorage | null = sessionStorageOrNull()): boolean {
  if (!storage) return false
  try {
    const preference = Object.fromEntries(Object.keys(fields).map((field) => [field, selection[field as keyof ConsultationState]]))
    storage.setItem(storageKey(accountId, selection.targetIcpId), JSON.stringify(preference))
    storage.setItem(storageKey(accountId), JSON.stringify(selection.targetIcpId))
    return true
  } catch { return false }
}

export function clearConsultationPreference(accountId: string, targetIcpId: string, storage: PreferenceStorage | null = sessionStorageOrNull()): void {
  try { storage?.removeItem(storageKey(accountId, targetIcpId)) } catch { /* Preferences are optional. */ }
}

export function clearAccountConsultationPreferences(accountId: string, storage: PreferenceStorage | null = sessionStorageOrNull()): void {
  if (!storage) return
  try {
    const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index))
    for (const key of keys) {
      if (!key?.startsWith(PREFIX)) continue
      try {
        const owner: unknown = JSON.parse(key.slice(PREFIX.length))
        if (Array.isArray(owner) && owner[0] === accountId) storage.removeItem(key)
      } catch { /* An unrelated/malformed preference cannot authorize a broader purge. */ }
    }
  } catch { /* No private data is stored here; failure does not block logout. */ }
}

export function writeConsultationSearch(search: string, selection: ConsultationState): string {
  const params = new URLSearchParams(search)
  for (const field of Object.keys(fields) as Array<keyof ConsultationState>) {
    const value = selection[field]
    if (value === null) params.delete(fields[field])
    else params.set(fields[field], value)
  }
  return params.size ? `?${params}` : ''
}

/** Reset consultation overrides while retaining the selected profile and list navigation. */
export function clearConsultationSearch(search: string): string {
  const params = new URLSearchParams(search)
  for (const field of ['offerCategory', 'subdivisionCode', 'minAmount', 'amountCurrency'] as const) {
    params.delete(fields[field])
  }
  return params.size ? `?${params}` : ''
}

/** A signed page cursor belongs to its old consultation context, not to the new selection. */
export function clearConsultationPagination(search: string): string {
  const params = new URLSearchParams(search)
  params.delete('cursor')
  params.delete('offset')
  return params.size ? `?${params}` : ''
}

export function safeInternalReturn(value: unknown): string | null {
  if (typeof value !== 'string' || !value.startsWith('/app/')) return null
  // Reject normalized traversal and backslashes before URL parsing can hide them.
  try {
    const decoded = decodeURIComponent(value.split(/[?#]/, 1)[0])
    // eslint-disable-next-line no-control-regex -- Explicitly reject control characters in redirect paths.
    if (/[\\\u0000-\u0020\u007f]/.test(value) || /[\\\u0000-\u001f\u007f]/.test(decoded)) return null
    if (decoded.split('/').some((part) => part === '.' || part === '..')) return null
    const url = new URL(value, 'https://kivou.invalid')
    return url.origin === 'https://kivou.invalid' && url.pathname.startsWith('/app/')
      ? `${url.pathname}${url.search}${url.hash}` : null
  } catch { return null }
}

export function signalDetailPath(signalKey: string, search = ''): string {
  const params = new URLSearchParams(search)
  const artifact = params.get('presentation_artifact_id')
  if (artifact !== null && !/^[a-f0-9]{64}$/.test(artifact)) params.delete('presentation_artifact_id')
  return `/app/signals/${encodeURIComponent(signalKey)}${params.size ? `?${params}` : ''}`
}
