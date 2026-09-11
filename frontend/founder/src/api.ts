import type {
  FounderOverview,
  FounderProspection,
  FounderProspectionFilters,
  FounderSession,
  FounderTunnelPeriod,
} from './types'

export class FounderApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'FounderApiError'
    this.status = status
  }
}

async function requestJson<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) {
    const message =
      response.status === 401 || response.status === 403
        ? 'Accès refusé par la frontière Founder.'
        : response.status === 503
          ? 'Les données Founder ne sont pas encore disponibles.'
          : 'Le service Founder est momentanément indisponible.'
    throw new FounderApiError(message, response.status)
  }
  return (await response.json()) as T
}

export function loadFounderSession(signal: AbortSignal): Promise<FounderSession> {
  return requestJson<FounderSession>('/api/founder/session', signal)
}

export function loadFounderOverview(
  weekOffset: number,
  signal: AbortSignal,
): Promise<FounderOverview>
export function loadFounderOverview(
  weekOffset: number,
  period: FounderTunnelPeriod,
  signal: AbortSignal,
): Promise<FounderOverview>
export function loadFounderOverview(
  weekOffset: number,
  periodOrSignal: FounderTunnelPeriod | AbortSignal,
  maybeSignal?: AbortSignal,
): Promise<FounderOverview> {
  const period = typeof periodOrSignal === 'string' ? periodOrSignal : 'last_7_days'
  const signal = typeof periodOrSignal === 'string' ? maybeSignal : periodOrSignal
  if (!signal) throw new TypeError('An AbortSignal is required')
  const query = new URLSearchParams({
    week_offset: String(weekOffset),
    period,
  })
  return requestJson<FounderOverview>(`/api/founder/overview?${query}`, signal)
}

export function loadFounderProspection(
  filters: FounderProspectionFilters,
  signal: AbortSignal,
): Promise<FounderProspection> {
  const query = new URLSearchParams({
    page: String(filters.page),
    page_size: '25',
  })
  if (filters.q) query.set('q', filters.q)
  if (filters.family) query.set('family', filters.family)
  if (filters.department) query.set('department', filters.department)
  if (filters.status) query.set('status', filters.status)
  return requestJson<FounderProspection>(`/api/founder/prospection?${query}`, signal)
}
