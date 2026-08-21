import { useI18n, interpolate, plural } from '../i18n'
import { Badge, Card } from '../components/Surfaces'
import { Button, ButtonLink } from '../components/Button'
import { CheckIcon } from '../assets/Icons'
import type { CataloguePlan, Currency, PlanCatalogue, PlanCode, PurchasablePlan } from '../api/types'
import styles from './PlanGrid.module.css'

/* La grille tarifaire — le backend est la SEULE source de prix.
 *
 * Aucun montant n'est écrit ici. `GET /billing/plans` renvoie les prix en
 * unités mineures, par devise, et `recommended` désigne Pro. Recopier la grille
 * dans le frontend créerait une seconde vérité qui divergerait au premier
 * changement tarifaire — exactement ce que les anciens 29/59/129 des maquettes
 * illustrent.
 *
 * L'offre Founding n'apparaît pas : elle est privée, et le catalogue public ne
 * la contient pas. Rien ici ne la reconstitue.
 */

export function PlanGrid({
  catalogue,
  variant,
  currency,
  currentPlan,
  onChoose,
  choosingPlan,
  disabled = false,
}: {
  catalogue: PlanCatalogue
  /** `public` renvoie vers l'inscription ; `app` déclenche le paiement. */
  variant: 'public' | 'app'
  currency?: Currency
  currentPlan?: PlanCode
  onChoose?: (plan: PurchasablePlan) => void
  choosingPlan?: PurchasablePlan | null
  disabled?: boolean
}) {
  const selected = currency ?? catalogue.currencies[0] ?? 'chf'

  return (
    <ul className={styles.grid}>
      {catalogue.plans.map((plan) => (
        <li key={plan.plan_code} className={styles.cell}>
          <PlanCard
            plan={plan}
            currency={selected}
            variant={variant}
            isCurrent={currentPlan === plan.plan_code}
            onChoose={onChoose}
            choosing={choosingPlan === plan.plan_code}
            disabled={disabled}
          />
        </li>
      ))}
    </ul>
  )
}

function PlanCard({
  plan,
  currency,
  variant,
  isCurrent,
  onChoose,
  choosing,
  disabled,
}: {
  plan: CataloguePlan
  currency: Currency
  variant: 'public' | 'app'
  isCurrent: boolean
  onChoose?: (plan: PurchasablePlan) => void
  choosing: boolean
  disabled: boolean
}) {
  const { t, money } = useI18n()
  const price = plan.monthly_price[currency]
  const name = t.billing.plans[plan.plan_code]

  return (
    <Card
      padding="lg"
      as="article"
      elevated={plan.recommended}
      className={`${styles.card} ${plan.recommended ? styles.recommended : ''} ${
        isCurrent ? styles.current : ''
      }`}
    >
      {/* Pro porte une bande Forest Green : c'est le centre visuel de la grille
          (docx §Cards, §Pricing). */}
      {plan.recommended ? <p className={styles.ribbon}>{t.billing.recommended}</p> : null}

      <div className={styles.head}>
        <h3 className={styles.name}>{name}</h3>
        <p className={styles.price}>
          {price ? (
            <>
              <span className={`${styles.amount} kivou-tabular`}>
                {money(price.amount_minor_units, price.currency)}
              </span>
              <span className={styles.interval}>{t.billing.perMonth}</span>
            </>
          ) : (
            <span className={styles.amount}>{t.billing.free}</span>
          )}
        </p>
        {isCurrent ? <Badge tone="positive">{t.billing.current}</Badge> : null}
      </div>

      <ul className={styles.features}>
        {describeEntitlements(plan, t).map((feature) => (
          <li key={feature}>
            <CheckIcon className={styles.featureIcon} aria-hidden="true" />
            {feature}
          </li>
        ))}
      </ul>

      <div className={styles.action}>
        {variant === 'public' ? (
          <ButtonLink
            to="/signup"
            variant={plan.recommended ? 'primary' : 'secondary'}
            fullWidth
          >
            {plan.purchasable ? interpolate(t.billing.choose, { plan: name }) : t.nav.signup}
          </ButtonLink>
        ) : plan.purchasable && !isCurrent ? (
          <Button
            variant={plan.recommended ? 'primary' : 'secondary'}
            fullWidth
            loading={choosing}
            disabled={disabled}
            onClick={() => onChoose?.(plan.plan_code as PurchasablePlan)}
          >
            {choosing ? t.billing.choosing : interpolate(t.billing.choose, { plan: name })}
          </Button>
        ) : null}
      </div>
    </Card>
  )
}

/* Traduit les capacités RENVOYÉES par l'API — et seulement celles qu'un client
 * peut réellement exercer aujourd'hui.
 *
 * Trois capacités du contrat ne sont PAS rendues, et c'est délibéré (P0-03 §14) :
 *
 *   — `export_level` : aucune route, aucune UI. Le champ décrit une intention
 *     de packaging, pas une fonctionnalité livrée ;
 *   — `filter_level` : l'API autorise bien `country` et `winner` selon le plan,
 *     mais le feed n'expose aucun de ces filtres. Vendre « Filtres avancés »
 *     enverrait chercher un écran qui n'existe pas ;
 *   — `territory_mode` et `max_territories_per_icp` : la limite n'est appliquée
 *     nulle part, donc « 1 territoire principal » décrit une restriction
 *     imaginaire — et rend absurde la montée vers « Plusieurs territoires ».
 *
 * Les champs restent dans le contrat : ils portent des décisions serveur
 * réelles, et `filter_level` autorise effectivement les filtres de l'API. Ce
 * qui disparaît est la PROMESSE COMMERCIALE, pas la donnée. Le jour où l'un de
 * ces parcours existe, sa ligne revient ici. */
function describeEntitlements(
  plan: CataloguePlan,
  t: ReturnType<typeof useI18n>['t'],
): string[] {
  const e = plan.entitlements
  const features: string[] = []

  features.push(
    interpolate(
      plural(e.max_active_icps, t.billing.entitlements.icpsOne, t.billing.entitlements.icpsOther),
      { count: e.max_active_icps },
    ),
  )

  if (e.granted_signals > 0) {
    features.push(
      interpolate(t.billing.entitlements.grantedSignals, { count: e.granted_signals }),
    )
  }

  if (e.history_scope === 'all_available') {
    features.push(t.billing.entitlements.historyAll)
  } else if (e.history_days && e.history_days > 0) {
    features.push(interpolate(t.billing.entitlements.historyWindow, { days: e.history_days }))
  } else {
    features.push(t.billing.entitlements.historyNone)
  }

  if (e.evidence_access) features.push(t.billing.entitlements.evidence)

  // `priority` et jamais « temps réel » : le backend a renommé cette cadence
  // précisément pour ne pas promettre une latence qu'aucun cron ne tient.
  features.push(
    e.alert_cadence === 'priority'
      ? t.billing.entitlements.alertPriority
      : e.alert_cadence === 'daily'
        ? t.billing.entitlements.alertDaily
        : e.alert_cadence === 'weekly'
          ? t.billing.entitlements.alertWeekly
          : t.billing.entitlements.alertNone,
  )

  return features
}
