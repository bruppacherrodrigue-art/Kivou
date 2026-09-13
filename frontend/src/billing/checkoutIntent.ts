/* Vers quel signal, dossier entreprise ou recherche annuaire revenir après
 * confirmation de l'accès. Identifiants et filtres publics uniquement.
 *
 * Ce que ce module N'EST PAS
 * ──────────────────────────
 * Il n'accorde aucun droit. Il ne prouve aucun paiement. Il ne déverrouille
 * rien. La seule autorité sur l'accès reste le serveur — `GET /billing/status`
 * pour le plan, `GET /signals/{key}` pour le signal. Si le détail répond
 * `locked` malgré une intention mémorisée, c'est `locked` qui s'affiche.
 *
 * Il mémorise une destination typée, le compte et une expiration d'une heure.
 * Les anciennes clés seules restent lisibles par migration. Rien du dossier
 * — ni entreprise gagnante, ni montant, ni besoin, ni preuve, ni source — ne
 * doit transiter par ce stockage : ce sont précisément les données que le
 * paywall protège, et les écrire dans le navigateur d'un compte qui n'y a pas
 * encore droit les livrerait sans que le serveur ait rien décidé.
 *
 * Éphémère par choix : `sessionStorage` meurt avec l'onglet. Une intention
 * d'achat n'a aucune raison de survivre à la session qui l'a formée.
 */

import { onSignOutStarted } from '../api/client'

/** Assez pour les clés API, sans permettre un contenu libre démesuré. */
export const MAXIMUM_SIGNAL_KEY_LENGTH = 128

const STORAGE_KEY = 'kivou.checkout-intent'

/* Les caractères de contrôle sont refusés : une clé en porte n'a aucune raison
 * d'exister, et l'une d'elles finirait dans un chemin d'URL. */
// eslint-disable-next-line no-control-regex
const CONTROL_CHARACTERS = /[\u0000-\u001F\u007F-\u009F]/

/** La clé si elle est utilisable, `null` sinon.
 *
 *  La validation porte sur la SÛRETÉ, jamais sur le sens : reconnaître ici la
 *  structure métier d'une clé reviendrait à rejeter demain une clé que l'API
 *  aurait légitimement changée. */
export function validateSignalKey(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (trimmed.length === 0) return null
  if (trimmed.length > MAXIMUM_SIGNAL_KEY_LENGTH) return null
  if (CONTROL_CHARACTERS.test(trimmed)) return null
  return trimmed
}

export function saveCheckoutIntent(signalKey: string): void {
  const valid = validateSignalKey(signalKey)
  if (valid === null) return
  try {
    sessionStorage.setItem(STORAGE_KEY, valid)
  } catch {
    // Navigation privée stricte, quota plein : perdre le retour au signal est
    // acceptable, interrompre le paiement ne l'est pas.
  }
}

/** L'intention mémorisée, relue avec la même défiance qu'une entrée réseau :
 *  le stockage est modifiable par l'utilisateur. */
export function readCheckoutIntent(): string | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    // Compatibility for old callers; production return navigation additionally
    // verifies account + expiry through readCheckoutReturn.
    if (raw?.startsWith('{')) {
      const saved = JSON.parse(raw)
      const target = validateCheckoutReturn(saved.target)
      return saved.version === 2 && saved.expiresAt > Date.now() && target?.kind === 'signal' ? target.signalKey : null
    }
    return validateSignalKey(raw)
  } catch {
    return null
  }
}

export function clearCheckoutIntent(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // Rien à faire : l'intention n'ouvre aucun droit, la perdre est sans effet.
  }
}

export type CheckoutReturnIntent =
  | { kind: 'signal'; signalKey: string; artifactId?: string }
  | { kind: 'company'; companyKey: string }
  | { kind: 'directory'; search: string }

/** One tab, one account, one hour. Identifiers/filters only, never dossier data. */
export const CHECKOUT_RETURN_TTL_MS = 60 * 60 * 1000

function pathKey(value: unknown): string | null {
  const key = validateSignalKey(value)
  return key === '.' || key === '..' ? null : key
}

export function validateCheckoutReturn(value: unknown): CheckoutReturnIntent | null {
  if (!value || typeof value !== 'object') return null
  const input = value as Record<string, unknown>
  if (input.kind === 'signal') {
    const signalKey = pathKey(input.signalKey)
    const artifactId = input.artifactId === undefined ? undefined : pathKey(input.artifactId)
    return signalKey && artifactId !== null ? { kind: 'signal', signalKey, ...(artifactId ? { artifactId } : {}) } : null
  }
  if (input.kind === 'company') {
    const companyKey = pathKey(input.companyKey)
    return companyKey ? { kind: 'company', companyKey } : null
  }
  if (input.kind === 'directory' && typeof input.search === 'string') {
    if (input.search.length > 1024 || (input.search && !input.search.startsWith('?')) || CONTROL_CHARACTERS.test(input.search)) return null
    const params = new URLSearchParams(input.search)
    const clean = new URLSearchParams()
    const q = params.get('q')
    if (q && q.length <= 120 && !CONTROL_CHARACTERS.test(q)) clean.set('q', q)
    const department = params.get('department')
    if (department && /^[A-Z0-9]{2,3}$/.test(department)) clean.set('department', department)
    const family = params.get('family')
    if (family && /^[a-z0-9_]{1,120}$/.test(family)) clean.set('family', family)
    const sort = params.get('sort')
    if (sort === 'name' || sort === 'city') clean.set('sort', sort)
    return { kind: 'directory', search: clean.size ? `?${clean}` : '' }
  }
  return null
}

export function saveCheckoutReturn(accountId: string, value: CheckoutReturnIntent): void {
  const target = validateCheckoutReturn(value)
  if (!target || !validateSignalKey(accountId)) return
  const createdAt = Date.now()
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 2, accountId, createdAt, expiresAt: createdAt + CHECKOUT_RETURN_TTL_MS, target })) } catch { /* Optional navigation continuity only. */ }
}

export function readCheckoutReturn(accountId: string): CheckoutReturnIntent | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    if (!raw.startsWith('{')) {
      const signalKey = pathKey(raw)
      if (!signalKey) return null
      const target: CheckoutReturnIntent = { kind: 'signal', signalKey }
      // The previous version had no account metadata; bind the one-time
      // migration now. The destination GET still decides access independently.
      saveCheckoutReturn(accountId, target)
      return target
    }
    const saved = JSON.parse(raw)
    if (saved.version !== 2 || saved.accountId !== accountId || !Number.isSafeInteger(saved.createdAt) || !Number.isSafeInteger(saved.expiresAt)
      || saved.createdAt > Date.now() || saved.expiresAt <= Date.now() || saved.expiresAt - saved.createdAt !== CHECKOUT_RETURN_TTL_MS) return null
    return validateCheckoutReturn(saved.target)
  } catch { return null }
}

export function checkoutReturnPath(intent: CheckoutReturnIntent): string {
  if (intent.kind === 'company') return `/app/companies/${encodeURIComponent(intent.companyKey)}`
  if (intent.kind === 'directory') return `/app/companies/directory${intent.search}`
  const query = intent.artifactId ? `?${new URLSearchParams({ presentation_artifact_id: intent.artifactId })}` : ''
  return `/app/signals/${encodeURIComponent(intent.signalKey)}${query}`
}

// Synchronous intent cleanup, even while POST /auth/logout remains pending.
onSignOutStarted(clearCheckoutIntent)
