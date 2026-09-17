/* Les appels, un par point d'entrée du backend.
 *
 * Chaque fonction correspond à une route réelle de `src/signals/api/`. Aucune
 * n'accepte ni ne transmet d'`account_id` : la propriété vient de la session
 * côté serveur, et l'envoyer depuis le navigateur serait au mieux redondant,
 * au pire une élévation de privilège.
 */
import { notifySignOutStarted, request } from './client'
import type { QueryParams } from './client'
import type {
  BillingStatus,
  CheckoutSession,
  CompanyProfile,
  CompanyListPage,
  CompanyContactResult,
  CompanyContactLookup,
  CompanyDirectoryEnrichment,
  CompanyContactStatus,
  DirectoryCompanyProfile,
  DashboardResponse,
  CompanyNoteResult,
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
  TargetIcpOptions,
  TargetIcpInput,
  UnifiedStatus,
  Interaction,
  NegativeReason,
  Relevance,
  CompanyDossierResponse,
  CompanyMembership,
  DirectorySearchPage,
  DirectoryOptions,
  ManualContactInput,
  ManualContactView,
  ProspectingQueryScope,
  SignalStatusResult,
} from './types'

export interface RequestControl { signal?: AbortSignal }
export interface ConsultationQuery extends QueryParams, ProspectingQueryScope {}

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

  claimAccess: (password: string, email?: string) =>
    request<Me>('/auth/claim-access', {
      method: 'POST',
      body: email ? { password, email } : { password },
    }),

  logout: () => {
    notifySignOutStarted()
    return request<void>('/auth/logout', { method: 'POST' })
  },

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
  list: (options: RequestControl = {}) => request<TargetIcp[]>('/target-icps', options),

  options: (options: RequestControl = {}) => request<TargetIcpOptions>('/target-icps/options', options),

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

export interface FeedQuery extends ConsultationQuery {
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
  q?: string | null
  sort?: 'recent' | 'amount' | null
}

export interface SignalDetailQuery extends ConsultationQuery {
  presentation_artifact_id?: string | null
}

export const signals = {
  feed: (query: FeedQuery = {}, options: RequestControl = {}) => request<FeedPage>('/signals', { query, ...options }),

  detail: (signalKey: string, query: SignalDetailQuery = {}, options: RequestControl = {}) =>
    request<SignalDetail>(`/signals/${encodeURIComponent(signalKey)}`, { query, ...options }),

  setStatus: (signalKey: string, status: UnifiedStatus, expectedRevision: number, options: RequestControl = {}) =>
    request<SignalStatusResult>(`/signals/${encodeURIComponent(signalKey)}/status`, {
      method: 'PUT', body: { status, expected_revision: expectedRevision }, ...options,
    }),
}

export const signalNotes = {
  read: (signalKey: string, options: RequestControl = {}) =>
    request<SignalNote & { revision: number }>(`/signals/${encodeURIComponent(signalKey)}/note`, options),

  write: (signalKey: string, note: string, expectedRevision?: number, options: RequestControl = {}) =>
    request<SignalNote & { revision: number }>(`/signals/${encodeURIComponent(signalKey)}/note`, {
      method: 'PUT',
      body: { note, expected_revision: expectedRevision }, ...options,
    }),
}

// ─── Entreprises ─────────────────────────────────────────────────────────────

export interface CompanyListQuery extends ConsultationQuery {
    view?: 'prospection'
    contact_status?: CompanyContactStatus[] | null
    q?: string | null
    sort?: 'recent' | 'amount' | null
    limit?: number
    cursor?: string | null
}
export interface DirectorySearchQuery extends QueryParams {
  q?: string | null
  department?: string | null
  family?: string | null
  sort?: 'name' | 'city'
  limit?: number
  cursor?: string | null
}

export const companies = {
  list: (query: CompanyListQuery = {}, options: RequestControl = {}) => request<CompanyListPage>('/companies', { query, ...options }),

  get: (companyKey: string) =>
    request<CompanyProfile>(`/companies/${encodeURIComponent(companyKey)}`),

  dossier: (companyKey: string, options: RequestControl = {}) =>
    request<CompanyDossierResponse>(`/companies/${encodeURIComponent(companyKey)}`, options),

  directorySearch: (query: DirectorySearchQuery = {}, options: RequestControl = {}) =>
    request<DirectorySearchPage>('/companies/directory', { query, ...options }),
  directoryOptions: (options: RequestControl = {}) =>
    request<DirectoryOptions>('/companies/directory/options', options),

  directoryGet: (siren: string, options: RequestControl = {}) =>
    request<DirectoryCompanyDossierResponse>(`/companies/directory/${encodeURIComponent(siren)}`, options),

  contact: (companyKey: string, status: CompanyContactStatus, options: RequestControl = {}) =>
    request<CompanyContactResult>(`/companies/${encodeURIComponent(companyKey)}/contact`, {
      method: 'POST',
      body: { status }, ...options,
    }),

  contactLookup: (companyKey: string, options: RequestControl = {}) =>
    request<CompanyContactLookup>(`/companies/${encodeURIComponent(companyKey)}/contact-lookup`, {
      method: 'POST', ...options,
    }),

  queueDirectoryEnrichment: (companyKey: string, options: RequestControl = {}) =>
    request<CompanyDirectoryEnrichment & { queued: boolean }>(
      `/companies/${encodeURIComponent(companyKey)}/directory-enrichment`,
      { method: 'POST', ...options },
    ),

  note: (companyKey: string, body: string, expectedRevision?: number, options: RequestControl = {}) =>
    request<CompanyNoteResult & { revision: number }>(`/companies/${encodeURIComponent(companyKey)}/note`, {
      method: 'PUT',
      body: { body, expected_revision: expectedRevision }, ...options,
    }),

  follow: (companyKey: string, options: RequestControl = {}) =>
    request<CompanyMembership & { company_key: string }>(`/companies/${encodeURIComponent(companyKey)}/prospection`, { method: 'PUT', body: {}, ...options }),

  manualContact: (companyKey: string, options: RequestControl = {}) =>
    request<ManualContactView>(`/companies/${encodeURIComponent(companyKey)}/manual-contact`, options),

  saveManualContact: (companyKey: string, payload: ManualContactInput, options: RequestControl = {}) =>
    request<ManualContactView>(`/companies/${encodeURIComponent(companyKey)}/manual-contact`, { method: 'PUT', body: payload, ...options }),

  deleteManualContact: (companyKey: string, expectedRevision: number, options: RequestControl = {}) =>
    request<ManualContactView>(`/companies/${encodeURIComponent(companyKey)}/manual-contact`, { method: 'DELETE', headers: { 'If-Match': `"${expectedRevision}"` }, ...options }),
}

type DirectoryCompanyDossierResponse = DirectoryCompanyProfile & import('./types').PrivateCompanyContext & { company_key: string }

export const dashboard = {
  get: (query: ConsultationQuery = {}, options: RequestControl = {}) => request<DashboardResponse>('/dashboard', { query, ...options }),
}

export const accountData = {
  export: () => request<Record<string, unknown>>('/account/export'),
  requestDeletion: () => request<{ scheduled_for: string }>('/account/deletion', {
    method: 'POST',
    body: { confirmation: 'SUPPRIMER' },
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

  status: (options: RequestControl = {}) => request<BillingStatus>('/billing/status', options),

  /** Le navigateur n'envoie QUE le plan et la devise. Aucun `price_id`, aucun
   *  coupon, aucun drapeau fondateur : le serveur choisit le prix. */
  checkout: (payload: { plan: PurchasablePlan; currency: 'eur' }) =>
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
