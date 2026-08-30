import type { PlanCode } from '../api/types'

const ROUTABLE_PLANS: readonly PlanCode[] = ['discovery', 'essential', 'pro', 'scale']

export function planFromSearch(search: string): PlanCode {
  const candidate = new URLSearchParams(search).get('plan')
  return ROUTABLE_PLANS.includes(candidate as PlanCode)
    ? (candidate as PlanCode)
    : 'discovery'
}

export function planSearch(plan: PlanCode): string {
  return `?plan=${encodeURIComponent(plan)}`
}
