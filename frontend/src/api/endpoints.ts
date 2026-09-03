/* Les appels, un par point d'entrée du backend.
 *
 * Chaque fonction correspond à une route réelle de `src/signals/api/`. Aucune
 * n'accepte ni ne transmet d'`account_id` : la propriété vient de la session
 * côté serveur, et l'envoyer depuis le navigateur serait au mieux redondant,
 * au pire une élévation de privilège.
 */
import { request } from './client'
import type { QueryParams } from './client'
import type {
  BillingStatus,
  CheckoutSession,
  CompanyProfile,
  CompanyListPage,
  CompanyContactResult,
  CompanyContactStatus,
  CompanyNoteResult,
  Currency,
  FeedPage,
  Freshness,
  Locale,
  Me,
  NotificationPreference,
  PlanCatalogue,
  PurchasablePlan,
  SignalDetail,
  SignalNote,
  TargetIcp,
  TargetIcpInput,
  UnifiedStatus,
  WeeklyCommercialCockpit,
  Interaction,
  NegativeReason,
  Relevance,
} from './types'

// ─── Authentification ────────────────────────────────────────────────────────

export const auth = {
  me: () => request<Me>('/me', { silentUnauthenticated: true }),

  updateLocale: (locale: Locale) =>
    request<Me>('/me', { method: 'PATCH', body: { locale } }),

  signup: (payload: {
    email: string
    password: string
    company_name: string
    locale: Locale
  }) => request<Me>('/auth/signup', { method: 'POST', body: payload }),

  login: (payload: { email: string; password: string }) =>
    request<Me>('/auth/login', { method: 'POST', body: payload }),

  logout: () => request<void>('/auth/logout', { method: 'POST' }),

  requestPasswordReset: (email: string) =>
    request<{ status: string }>('/auth/password-reset/request', {
      method: 'POST',
      body: { email },
    }),

  confirmPasswordReset: (payload: { reset_token: string; new_password: string }) =>
    request<{ status: string }>('/auth/password-reset/confirm', {
      method: 'POST',
      body: payload,
    }),
}

// ─── Profils de ciblage ──────────────────────────────────────────────────────

export const icps = {
  list: () => request<TargetIcp[]>('/target-icps'),

  get: (id: string) => request<TargetIcp>(`/target-icps/${encodeURIComponent(id)}`),

  create: (payload: { label: string; customer_input: TargetIcpInput }) =>
    request<TargetIcp>('/target-icps', { method: 'POST', body: payload }),

  update: (id: string, payload: { label?: string; customer_input?: TargetIcpInput }) =>
    request<TargetIcp>(`/target-icps/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: payload,
    }),
}

// ─── Signaux ─────────────────────────────────────────────────────────────────

export interface FeedQuery extends QueryParams {
  view?: 'recent' | 'history'
  freshness?: Freshness
  target_icp_id?: string | null
  country?: string | null
  subdivision_code?: string | null
  /** Répétable côté backend (`status=a&status=b`) — jamais une liste séparée
   *  par des virgules. */
  status?: UnifiedStatus[] | null
  /** Le nom que porte désormais le filtre de récence — `status` continue
   *  d'accepter l'ancien vocabulaire par compatibilité. */
  recency_status?: string | null
  cpv_prefix?: string | null
  date_from?: string | null
  date_to?: string | null
  winner?: string | null
  limit?: number
  offset?: number
  cursor?: string | null
}

export interface SignalDetailQuery extends QueryParams {
  presentation_artifact_id?: string | null
}

export const signals = {
  feed: (query: FeedQuery = {}) => request<FeedPage>('/signals', { query }),

  detail: (signalKey: string, query: SignalDetailQuery = {}) =>
    request<SignalDetail>(`/signals/${encodeURIComponent(signalKey)}`, { query }),
}

export const signalNotes = {
  read: (signalKey: string) =>
    request<SignalNote>(`/signals/${encodeURIComponent(signalKey)}/note`),

  write: (signalKey: string, note: string) =>
    request<SignalNote>(`/signals/${encodeURIComponent(signalKey)}/note`, {
      method: 'PUT',
      body: { note },
    }),
}

// ─── Entreprises ─────────────────────────────────────────────────────────────

export const companies = {
  list: (query: {
    contact_status?: CompanyContactStatus[] | null
    q?: string | null
    limit?: number
    cursor?: string | null
  } = {}) => request<CompanyListPage>('/companies', { query }),

  get: (companyKey: string) =>
    request<CompanyProfile>(`/companies/${encodeURIComponent(companyKey)}`),

  contact: (companyKey: string, status: CompanyContactStatus) =>
    request<CompanyContactResult>(`/companies/${encodeURIComponent(companyKey)}/contact`, {
      method: 'POST',
      body: { status },
    }),

  note: (companyKey: string, body: string) =>
    request<CompanyNoteResult>(`/companies/${encodeURIComponent(companyKey)}/note`, {
      method: 'PUT',
      body: { body },
    }),
}

// ─── Retour client ───────────────────────────────────────────────────────────

interface FeedbackEnvelope {
  signal_id: string
  interaction: Interaction | null
}

export const feedback = {
  read: (signalKey: string) =>
    request<FeedbackEnvelope>(`/signals/${encodeURIComponent(signalKey)}/feedback`),

  write: (
    signalKey: string,
    payload: { relevance: Relevance; reason?: NegativeReason | null; note?: string | null },
  ) =>
    request<FeedbackEnvelope>(`/signals/${encodeURIComponent(signalKey)}/feedback`, {
      method: 'PUT',
      body: payload,
    }),

  markContacted: (signalKey: string) =>
    request<FeedbackEnvelope & { recorded: boolean }>(
      `/signals/${encodeURIComponent(signalKey)}/contacted`,
      { method: 'POST' },
    ),
}

// ─── Facturation ─────────────────────────────────────────────────────────────

export const billing = {
  plans: () => request<PlanCatalogue>('/billing/plans'),

  status: () => request<BillingStatus>('/billing/status'),

  /** Le navigateur n'envoie QUE le plan et la devise. Aucun `price_id`, aucun
   *  coupon, aucun drapeau fondateur : le serveur choisit le prix. */
  checkout: (payload: { plan: PurchasablePlan; currency: Currency }) =>
    request<CheckoutSession>('/billing/checkout', { method: 'POST', body: payload }),

  portal: () => request<{ portal_url: string }>('/billing/portal', { method: 'POST' }),
}

// ─── Notifications ───────────────────────────────────────────────────────────

export const notifications = {
  read: () => request<NotificationPreference>('/notification-preferences'),

  update: (payload: { email_enabled?: boolean; notification_email?: string | null }) =>
    request<NotificationPreference>('/notification-preferences', {
      method: 'PATCH',
      body: payload,
    }),
}

// ─── Cockpit commercial interne ─────────────────────────────────────────────

export const cockpit = {
  weekly: (weekOffset = 0) =>
    request<WeeklyCommercialCockpit>('/internal/commercial-cockpit', {
      query: { week_offset: weekOffset },
    }),
}
