import { ApiError } from './client'
import type { Dictionary } from '../i18n/fr'

/* Traduire un code d'erreur backend en ÉTAT PRODUIT.
 *
 * Le backend garantit des codes stables ; le message qu'il joint est
 * volontairement générique et rédigé pour un journal, pas pour un client. Le
 * frontend teste donc le code et rend sa propre formulation. Aucun message
 * serveur brut, aucune trace, aucune erreur SQL n'atteint l'écran (§35).
 */

export interface ErrorCopy {
  title: string
  body?: string
}

export function describeError(error: unknown, t: Dictionary): ErrorCopy {
  if (!(error instanceof ApiError)) {
    return { title: t.errors.genericTitle, body: t.errors.genericBody }
  }

  switch (error.code) {
    case 'network_error':
      return { title: t.errors.networkTitle, body: t.errors.networkBody }
    case 'invalid_credentials':
      return { title: t.errors.invalidCredentials }
    case 'email_already_used':
      return { title: t.errors.emailAlreadyUsed }
    case 'unsupported_locale':
      return { title: t.errors.unsupportedLocale }
    case 'invalid_reset_token':
      return { title: t.errors.invalidResetToken }
    case 'target_icp_not_found':
    case 'signal_not_found':
      return { title: t.errors.targetIcpNotFound }
    case 'signal_not_accessible':
      return { title: t.errors.signalNotAccessible }
    case 'filter_not_entitled':
      return { title: t.errors.filterNotEntitled }
    case 'csrf_origin_rejected':
      return { title: t.errors.csrfRejected }
    case 'billing_unavailable':
      return {
        title: t.billing.errors.unavailableTitle,
        body: t.billing.errors.unavailableBody,
      }
    case 'already_subscribed':
    case 'billing_subscription_conflict':
      return {
        title: t.billing.errors.alreadySubscribedTitle,
        body: t.billing.errors.alreadySubscribedBody,
      }
    case 'checkout_in_progress':
      return {
        title: t.billing.errors.checkoutInProgressTitle,
        body: t.billing.errors.checkoutInProgressBody,
      }
    case 'no_billing_customer':
      return {
        title: t.billing.errors.noCustomerTitle,
        body: t.billing.errors.noCustomerBody,
      }
    case 'invalid_notification_email':
      return { title: t.notifications.invalidEmail }
    case 'validation_error':
    case 'invalid_input':
    case 'invalid_feedback':
      return { title: t.errors.validationTitle }
    case 'not_authenticated':
      return { title: t.auth.sessionExpired }
    default:
      return { title: t.errors.genericTitle, body: t.errors.genericBody }
  }
}

/** Le message attaché à un champ précis d'un formulaire, s'il en existe un. */
export function fieldError(error: unknown, field: string): string | null {
  if (!(error instanceof ApiError)) return null
  const match = error.fields.find((entry) => entry.field === field)
  return match ? match.message : null
}
