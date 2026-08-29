import type { FounderOverview, FounderSession } from './types'

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
): Promise<FounderOverview> {
  const query = new URLSearchParams({ week_offset: String(weekOffset) })
  return requestJson<FounderOverview>(`/api/founder/overview?${query}`, signal)
}
