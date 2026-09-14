import type { CataloguePlan } from '../api/types'

// Subscription prices come from the EUR catalogue entry, never from a conversion.
// Keep historical/source currencies in API types for faithful billing and market data.
export const SUBSCRIPTION_CURRENCY = 'eur' as const

export function subscriptionPrice(plan: CataloguePlan) {
  const price = plan.monthly_price[SUBSCRIPTION_CURRENCY]
  return price?.currency.toLowerCase() === SUBSCRIPTION_CURRENCY ? price : null
}
