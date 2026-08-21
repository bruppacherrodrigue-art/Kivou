/* Vers quel signal revenir après un paiement confirmé.
 *
 * Ce que ce module N'EST PAS
 * ──────────────────────────
 * Il n'accorde aucun droit. Il ne prouve aucun paiement. Il ne déverrouille
 * rien. La seule autorité sur l'accès reste le serveur — `GET /billing/status`
 * pour le plan, `GET /signals/{key}` pour le signal. Si le détail répond
 * `locked` malgré une intention mémorisée, c'est `locked` qui s'affiche.
 *
 * Il ne mémorise qu'une chose : la clé du signal verrouillé qui a déclenché le
 * parcours d'achat, pour pouvoir y ramener le client. Rien du signal lui-même
 * — ni entreprise gagnante, ni montant, ni besoin, ni preuve, ni source — ne
 * doit transiter par ce stockage : ce sont précisément les données que le
 * paywall protège, et les écrire dans le navigateur d'un compte qui n'y a pas
 * encore droit les livrerait sans que le serveur ait rien décidé.
 *
 * Éphémère par choix : `sessionStorage` meurt avec l'onglet. Une intention
 * d'achat n'a aucune raison de survivre à la session qui l'a formée.
 */

/** Assez pour toute clé que l'API produit, assez peu pour qu'aucune valeur
 *  aberrante ne s'installe dans le stockage. */
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
    return validateSignalKey(sessionStorage.getItem(STORAGE_KEY))
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
