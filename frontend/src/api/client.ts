/* La frontière HTTP — une seule, et rien ne passe à côté.
 *
 * Aucun composant n'appelle `fetch` directement. Cette contrainte n'est pas
 * cosmétique : c'est ici que vivent la gestion du 401, la lecture des codes
 * d'erreur stables et la garantie que le cookie de session accompagne chaque
 * requête. Un `fetch` égaré dans un composant contournerait les trois.
 *
 * Les URL sont RELATIVES. Le frontend et l'API partagent une origine en
 * production (https://kivou.eu) ; en développement, le proxy Vite reproduit
 * cette condition. Aucune URL absolue, aucune variable d'environnement d'API
 * n'est donc nécessaire — et aucun jeton n'est jamais posé côté navigateur :
 * l'authentification reste le cookie HttpOnly posé par le serveur.
 */

/** Les codes d'erreur déclarés par `signals.api.errors.ERROR_CODES`. */
export type ApiErrorCode =
  | 'email_already_used'
  | 'invalid_credentials'
  | 'unsupported_locale'
  | 'invalid_reset_token'
  | 'target_icp_not_found'
  | 'territory_limit_exceeded'
  | 'not_authenticated'
  | 'csrf_origin_rejected'
  | 'invalid_input'
  | 'signal_not_found'
  | 'billing_unavailable'
  | 'invalid_webhook_signature'
  | 'unknown_plan'
  | 'plan_not_purchasable'
  | 'price_not_configured'
  | 'already_subscribed'
  | 'no_billing_customer'
  | 'stripe_mode_mismatch'
  | 'founding_not_available'
  | 'filter_not_entitled'
  | 'billing_error'
  | 'billing_subscription_conflict'
  | 'checkout_in_progress'
  | 'invalid_feedback'
  | 'signal_not_accessible'
  | 'invalid_notification_email'
  /** Panne réseau ou réponse illisible : ce code n'existe pas côté serveur. */
  | 'network_error'
  /** Erreur de validation FastAPI (422 pydantic), qui n'a pas de `code`. */
  | 'validation_error'

export interface FieldError {
  field: string
  message: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: ApiErrorCode
  /** Champs supplémentaires renvoyés par le backend (`filter`, `expires_at`…). */
  readonly extra: Record<string, unknown>
  /** Détail par champ, reconstruit depuis le 422 de pydantic. */
  readonly fields: FieldError[]

  constructor(
    status: number,
    code: ApiErrorCode,
    message: string,
    extra: Record<string, unknown> = {},
    fields: FieldError[] = [],
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.extra = extra
    this.fields = fields
  }

  get isUnauthenticated(): boolean {
    return this.status === 401 || this.code === 'not_authenticated'
  }
}

type Listener = () => void
const unauthenticatedListeners = new Set<Listener>()

/** Prévient l'application qu'une session n'est plus valable.
 *
 * Le nettoyage vit dans la session, pas ici : la frontière HTTP signale, elle
 * ne navigue pas. C'est ce qui évite la boucle « 401 → redirection → requête →
 * 401 » quand plusieurs appels échouent en même temps. */
export function onUnauthenticated(listener: Listener): () => void {
  unauthenticatedListeners.add(listener)
  return () => unauthenticatedListeners.delete(listener)
}

export type QueryValue = string | number | boolean | null | undefined
export type QueryParams = Record<string, QueryValue>

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  query?: QueryParams
  /** Coupe la diffusion du 401 — utilisé par le seul appel qui a le droit
   *  d'échouer sans conséquence : la vérification de session au démarrage. */
  silentUnauthenticated?: boolean
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === '') continue
    params.set(key, String(value))
  }
  const serialised = params.toString()
  return serialised ? `${path}?${serialised}` : path
}

/** Reconstruit des erreurs par champ depuis le 422 de pydantic. */
function readValidationDetail(detail: unknown): FieldError[] {
  if (!Array.isArray(detail)) return []
  const fields: FieldError[] = []
  for (const entry of detail) {
    if (typeof entry !== 'object' || entry === null) continue
    const record = entry as { loc?: unknown; msg?: unknown }
    const loc = Array.isArray(record.loc) ? record.loc : []
    // `loc` vaut ["body", "email"] : le premier segment est la source, pas le champ.
    const field = loc.length > 1 ? String(loc[loc.length - 1]) : String(loc[0] ?? '')
    fields.push({ field, message: typeof record.msg === 'string' ? record.msg : '' })
  }
  return fields
}

async function readError(response: Response): Promise<ApiError> {
  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    // Corps vide ou non-JSON : le statut reste la seule information fiable.
  }

  const detail =
    typeof payload === 'object' && payload !== null && 'detail' in payload
      ? (payload as { detail: unknown }).detail
      : payload

  if (Array.isArray(detail)) {
    return new ApiError(response.status, 'validation_error', '', {}, readValidationDetail(detail))
  }

  if (typeof detail === 'object' && detail !== null && 'code' in detail) {
    const { code, message, ...extra } = detail as {
      code: string
      message?: string
      [key: string]: unknown
    }
    return new ApiError(
      response.status,
      code as ApiErrorCode,
      typeof message === 'string' ? message : '',
      extra,
    )
  }

  const fallback: ApiErrorCode = response.status === 401 ? 'not_authenticated' : 'network_error'
  return new ApiError(response.status, fallback, '')
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, silentUnauthenticated = false } = options

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      // Le cookie de session est HttpOnly : il n'est lisible par aucun script,
      // et `same-origin` est ce qui le fait voyager malgré tout.
      credentials: 'same-origin',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'network_error', '')
  }

  if (response.status === 401 && !silentUnauthenticated) {
    for (const listener of unauthenticatedListeners) listener()
  }

  if (!response.ok) throw await readError(response)

  if (response.status === 204) return undefined as T
  const text = await response.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}
