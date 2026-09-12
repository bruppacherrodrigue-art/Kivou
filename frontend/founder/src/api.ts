import type {
  FounderOverview,
  FounderProspection,
  FounderProspectionActionList,
  FounderProspectionActionStatus,
  FounderProspectionCorrectionChanges,
  FounderProspectionCorrectionResponse,
  FounderProspectionFilters,
  FounderProspectionRejectionReason,
  FounderProspectionRejectionResponse,
  FounderProspectionSendResponse,
  FounderSession,
  FounderSystem,
  FounderProspectionTargetResponse,
  FounderTunnelPeriod,
} from './types'

export class FounderApiError extends Error {
  readonly status: number
  readonly code: string | null
  readonly targetIds: string[]

  constructor(message: string, status: number, code: string | null = null, targetIds: string[] = []) {
    super(message)
    this.name = 'FounderApiError'
    this.status = status
    this.code = code
    this.targetIds = targetIds
  }
}

type FounderActionErrorPayload = {
  detail?: {
    code?: unknown
    message?: unknown
    target_ids?: unknown
  }
}

async function requestActionJson<T>(url: string, body: unknown, fallbackMessage: string): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    let payload: FounderActionErrorPayload | null = null
    try {
      payload = (await response.json()) as FounderActionErrorPayload
    } catch {
      // A reverse-proxy failure may not return the API error envelope.
    }
    const detail = payload?.detail
    const code = typeof detail?.code === 'string' ? detail.code : null
    const message = typeof detail?.message === 'string' ? detail.message : fallbackMessage
    const targetIds = Array.isArray(detail?.target_ids)
      ? detail.target_ids.filter((value): value is string => typeof value === 'string')
      : []
    throw new FounderApiError(message, response.status, code, targetIds)
  }
  return (await response.json()) as T
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

export function loadFounderSystem(signal: AbortSignal): Promise<FounderSystem> {
  return requestJson<FounderSystem>('/api/founder/system', signal)
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
  if (filters.reverification_reason) query.set('reason', filters.reverification_reason)
  return requestJson<FounderProspection>(`/api/founder/prospection?${query}`, signal)
}

export function loadFounderProspectionActions(
  status: Extract<FounderProspectionActionStatus, 'pending_review' | 'approved'>,
  signal: AbortSignal,
  page = 1,
): Promise<FounderProspectionActionList> {
  const query = new URLSearchParams({ status, page: String(page), page_size: '25' })
  return requestJson<FounderProspectionActionList>(
    `/api/founder/actions/prospection/list?${query}`,
    signal,
  )
}

export async function approveFounderProspect(
  targetId: string,
  expectedVersion: number,
): Promise<FounderProspectionTargetResponse> {
  return requestActionJson<FounderProspectionTargetResponse>(
    '/api/founder/actions/prospection/approve',
    { target_id: targetId, expected_version: expectedVersion },
    'La validation a échoué.',
  )
}

export async function correctFounderProspect(
  targetId: string,
  expectedVersion: number,
  changes: FounderProspectionCorrectionChanges,
): Promise<FounderProspectionCorrectionResponse> {
  return requestActionJson<FounderProspectionCorrectionResponse>(
    '/api/founder/actions/prospection/correct',
    {
      target_id: targetId,
      expected_version: expectedVersion,
      changes,
    },
    'La correction a échoué.',
  )
}

export async function rejectFounderProspect(
  targetId: string,
  expectedVersion: number,
  reason: FounderProspectionRejectionReason,
  comment?: string,
): Promise<FounderProspectionRejectionResponse> {
  const body: Record<string, string | number> = {
    target_id: targetId,
    expected_version: expectedVersion,
    reason,
  }
  if (comment) body.comment = comment
  return requestActionJson<FounderProspectionRejectionResponse>(
    '/api/founder/actions/prospection/reject',
    body,
    'L’écartement a échoué.',
  )
}

export async function sendFounderProspects(
  requestId: string,
  targets: Array<{ target_id: string; expected_version: number }>,
): Promise<FounderProspectionSendResponse> {
  return requestActionJson<FounderProspectionSendResponse>(
    '/api/founder/actions/prospection/send',
    { request_id: requestId, targets },
    'L’envoi a échoué.',
  )
}
