import { useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { billing } from '../../api/endpoints'
import { subscriptionPrice } from '../../billing/subscriptionPricing'
import { useCurrentUser } from '../../auth/SessionProvider'
import { validateCheckoutReturn, type CheckoutReturnIntent } from '../../billing/checkoutIntent'
import { useI18n } from '../../i18n'
import { useResource } from '../../presentation/dashboard/resources'
import { DetailFrame } from './DetailFrame'
import styles from '../Prospecting.module.css'

export function UpgradeDialog(props: { onClose: () => void; intent: CheckoutReturnIntent; planCode?: 'essential' }) {
  const me = useCurrentUser()
  return <AccountUpgrade key={me.account_id} {...props} accountId={me.account_id} />
}

function AccountUpgrade({ onClose, intent, accountId, planCode }: { onClose: () => void; intent: CheckoutReturnIntent; accountId: string; planCode?: 'essential' }) {
  const { locale, money, t } = useI18n()
  const fr = locale === 'fr'
  const navigate = useNavigate()
  const load = useCallback(async () => {
    const [catalogue, status] = await Promise.all([billing.plans(), billing.status()])
    return { catalogue, status }
  }, [])
  const resource = useResource(load)
  const target = validateCheckoutReturn(intent)
  const state = { checkoutIntent: target, checkoutAccountId: accountId }
  const canChoose = resource.data?.status.billing_action === 'choose_plan'
  return <DetailFrame title={fr ? 'Choisir une offre' : 'Choose a plan'} onClose={onClose} compact>
    <h2>{fr ? 'Votre prospection, avec les bons accès.' : 'Your prospecting, with the right access.'}</h2>
    <p className={styles.muted}>{fr ? 'Consultez les offres disponibles. Le prix, les limites et vos droits sont confirmés par Kivou avant tout paiement.' : 'Review the available plans. Kivou confirms prices, limits and your access before any payment.'}</p>
    {resource.loading ? <p role="status">{fr ? 'Chargement des offres…' : 'Loading plans…'}</p>
      : resource.error ? <div><p role="alert" className={styles.error}>{fr ? 'Les offres ne sont pas disponibles pour le moment.' : 'Plans are temporarily unavailable.'}</p><button className={styles.button} onClick={() => void resource.retry()}>{fr ? 'Réessayer' : 'Retry'}</button></div>
        : !canChoose ? <Link className={styles.primary} to="/app/billing" state={state}>{fr ? 'Gérer ma facturation' : 'Manage billing'}</Link>
          : <div className={styles.form}>{resource.data?.catalogue.plans.filter((plan) => plan.purchasable && plan.plan_code !== 'discovery' && (!planCode || plan.plan_code === planCode)).map((plan) => {
            const price = subscriptionPrice(plan)
            if (!price) return null
            const name = t.billing.plans[plan.plan_code]
            return <section className={styles.panel} key={plan.plan_code}>
              <div className={styles.holder}><h3>{name}</h3><p>{money(price.amount_minor_units, price.currency.toUpperCase())} {fr ? '/ mois' : '/ month'}</p>
                <p className={styles.muted}>{plan.entitlements.max_active_icps} {fr ? 'profil(s) actif(s)' : 'active profile(s)'} · {plan.entitlements.history_days === null ? (fr ? 'Tout l’historique disponible' : 'All available history') : `${plan.entitlements.history_days} ${fr ? 'jours d’historique' : 'days of history'}`}</p>
                <button className={styles.primary} disabled={!target} onClick={() => navigate(`/app/billing?plan=${plan.plan_code}`, { state })}>{fr ? `Choisir ${name}` : `Choose ${name}`}</button>
              </div>
            </section>
          })}</div>}
    <p className={styles.muted}>{fr ? 'Aucun paiement n’est lancé depuis cette fenêtre.' : 'This dialog does not start a payment.'}</p>
  </DetailFrame>
}
