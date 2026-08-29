import { BUYER_TRADES, OFFER_KINDS } from '../../api/types'
import type { BuyerTrade, OfferKind, TargetIcpInput } from '../../api/types'
import { MVP_THRESHOLD_CURRENCIES, MVP_TERRITORIES } from '../../api/capabilities'
import { fr } from '../../i18n/fr'
import type { Dictionary } from '../../i18n/fr'
import { en } from '../../i18n/en'

export type TargetingField = 'offers' | 'buyer_trades' | 'territories' | 'threshold'

export class UnknownTargetingToken extends Error {
  readonly field: TargetingField
  readonly token: string

  constructor(field: TargetingField, token: string) {
    super(`${field}: ${token}`)
    this.field = field
    this.token = token
  }
}

export interface ReferenceTargetingDraft {
  name: string
  offer: string
  precision: string
  companies: string
  territory: string
  terms: string
  minAmount: string
  currency: string
}

const normalized = (value: string) => value.trim().toLocaleLowerCase('fr')
const tokens = (value: string) => [
  ...new Set(value.split(',').map((item) => item.trim()).filter(Boolean)),
]

function resolveCodes<T extends string>(
  raw: string,
  field: TargetingField,
  codes: readonly T[],
  labels: readonly Record<T, string>[],
): T[] {
  const lookup = new Map<string, T>()
  for (const code of codes) {
    lookup.set(normalized(code), code)
    for (const dictionary of labels) lookup.set(normalized(dictionary[code]), code)
  }
  const resolved = tokens(raw).map((token) => {
    const code = lookup.get(normalized(token))
    if (!code) throw new UnknownTargetingToken(field, token)
    return code
  })
  return [...new Set(resolved)]
}

export function toTargetIcpPayload(
  draft: ReferenceTargetingDraft,
  dictionary: Dictionary,
  previous?: TargetIcpInput,
): { label: string; customer_input: TargetIcpInput } {
  const territoryLookup = new Map<string, string>()
  for (const item of MVP_TERRITORIES) {
    for (const value of [item.code, item.fr, item.en]) {
      territoryLookup.set(normalized(value), item.code)
    }
  }
  const territories = [
    ...new Set(
      tokens(draft.territory).map((token) => {
        const code = territoryLookup.get(normalized(token))
        if (!code) throw new UnknownTargetingToken('territories', token)
        return code
      }),
    ),
  ]

  const currency = draft.currency.trim().toUpperCase()
  const minimum = Number(draft.minAmount)
  if (
    draft.minAmount.trim() === '' ||
    !MVP_THRESHOLD_CURRENCIES.includes(currency) ||
    !Number.isFinite(minimum) ||
    minimum < 0
  ) {
    throw new UnknownTargetingToken(
      'threshold',
      `${draft.minAmount} ${draft.currency}`.trim(),
    )
  }

  const previousThreshold = previous?.minimum_contract_value
  const preservedMaximum = previousThreshold?.maximum_amount ?? null
  if (
    preservedMaximum !== null &&
    (previousThreshold?.currency.trim().toUpperCase() !== currency || minimum > preservedMaximum)
  ) {
    throw new UnknownTargetingToken(
      'threshold',
      `${draft.minAmount} ${draft.currency}`.trim(),
    )
  }

  const offer = draft.offer.trim()
  const precision = draft.precision.trim()
  return {
    label: draft.name.trim(),
    customer_input: {
      offer_summary: precision ? `${offer}\n\n${precision}` : offer,
      offers: resolveCodes<OfferKind>(draft.terms, 'offers', OFFER_KINDS, [
        dictionary.offers,
        fr.offers,
        en.offers,
      ]),
      secondary_offers: previous?.secondary_offers ?? [],
      buyer_trades: resolveCodes<BuyerTrade>(
        draft.companies,
        'buyer_trades',
        BUYER_TRADES,
        [dictionary.trades, fr.trades, en.trades],
      ),
      secondary_buyer_trades: previous?.secondary_buyer_trades ?? [],
      territories,
      minimum_contract_value: {
        currency,
        minimum_amount: minimum,
        maximum_amount: preservedMaximum,
      },
    },
  }
}
