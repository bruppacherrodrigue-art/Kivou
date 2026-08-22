import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useI18n, interpolate } from '../i18n'
import { Badge, Callout, Card, SectionHeading, Skeleton } from '../components/Surfaces'
import { Button } from '../components/Button'
import { PlanGrid } from '../billing/PlanGrid'
import {
  clearCheckoutIntent,
  saveCheckoutIntent,
  validateSignalKey,
} from '../billing/checkoutIntent'
import { billing } from '../api/endpoints'
import { ApiError } from '../api/client'
import { describeError } from '../api/errorCopy'
import type { BillingStatus, Currency, PlanCatalogue, PurchasablePlan } from '../api/types'
import styles from './Billing.module.css'

/* La page de facturation.
 *
 * `billing_action` décide, `plan_code` décrit
 * ───────────────────────────────────────────
 * Deux champs, deux questions, et les confondre coûte de l'argent réel :
 *
 *     plan_code       →  quels droits le compte a-t-il MAINTENANT ?
 *     billing_action  →  quelle action de facturation est SÛRE maintenant ?
 *
 * Un compte `past_due` vaut `discovery` exactement comme un compte qui n'a
 * jamais rien payé — mais il porte un abonnement facturé. Brancher l'écran sur
 * `plan_code`, comme il le faisait, lui proposait « Choisir Pro » : au mieux un
 * 409, au pire une seconde facture pour un client qui n'a rien demandé de tel.
 *
 * Le frontend ne rejoue donc AUCUNE règle d'autorisation. Il ne connaît ni
 * `TERMINAL_STATUSES`, ni `PAYING_STATUSES`, ni `is_open_subscription()`, et ne
 * déduit rien de `subscription_status` — qu'il se contente d'AFFICHER.
 *
 * Le frontend n'envoie QUE `{ plan, currency }`. Aucun `price_id`, aucun
 * coupon, aucun drapeau fondateur : le montant n'est pas négociable depuis un
 * navigateur.
 *
 * La devise est un CHOIX EXPLICITE. La déduire de la langue ferait payer un
 * client suisse anglophone en euros.
 *
 * Kivou ne reconstruit aucun écran de gestion d'abonnement : moyen de paiement,
 * factures et résiliation vivent dans le portail du prestataire.
 */
export function Billing() {
  const { t, date } = useI18n()
  const location = useLocation()
  const [catalogue, setCatalogue] = useState<PlanCatalogue | null>(null)
  const [status, setStatus] = useState<BillingStatus | null>(null)
  const [currency, setCurrency] = useState<Currency>('chf')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [actionError, setActionError] = useState<unknown>(null)
  const [choosing, setChoosing] = useState<PurchasablePlan | null>(null)
  const [openingPortal, setOpeningPortal] = useState(false)

  /* Verrou SYNCHRONE. `setChoosing` planifie un rendu ; il ne ferme pas la
   * fenêtre entre deux clics du même tour de boucle. Le backend réserve déjà la
   * place avant d'appeler Stripe, mais une seconde requête partie d'ici
   * produirait un 409 que le client n'a aucune raison de voir. */
  const busyRef = useRef(false)

  /* Le signal verrouillé qui a déclenché la venue ici, s'il y en a un.
   * SEULE sa clé voyage — jamais l'entreprise, le montant, le besoin ni la
   * preuve, qui sont précisément ce que le paywall protège. */
  const lockedSignalKey = validateSignalKey(
    (location.state as { lockedSignalKey?: unknown } | null)?.lockedSignalKey,
  )

  useEffect(() => {
    let active = true
    Promise.all([billing.plans(), billing.status()])
      .then(([plans, billingStatus]) => {
        if (!active) return
        setCatalogue(plans)
        setStatus(billingStatus)
        // Une devise déjà facturée s'impose : on ne propose pas de changer la
        // devise d'un abonnement en cours depuis cet écran.
        if (billingStatus.currency === 'chf' || billingStatus.currency === 'eur') {
          setCurrency(billingStatus.currency)
        }
      })
      .catch((caught) => {
        if (active) setError(caught)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  async function startCheckout(plan: PurchasablePlan) {
    if (busyRef.current) return
    busyRef.current = true
    setActionError(null)
    setChoosing(plan)
    try {
      const session = await billing.checkout({ plan, currency })
      /* L'intention n'est mémorisée qu'APRÈS un paiement réellement ouvert.
       * L'écrire avant laisserait une intention orpheline derrière chaque
       * tentative refusée — et elle survivrait à un parcours qui n'a jamais eu
       * lieu. Elle n'accorde aucun droit : le retour au signal reste soumis à
       * ce que le serveur répondra.
       *
       * L'effacement PRÉCÈDE l'écriture, et il est inconditionnel. Un paiement
       * lancé sans signal doit remplacer une intention précédente par AUCUNE :
       * sans cela, une clé abandonnée dans le même onglet — retour navigateur,
       * paiement repris plus tard — ressurgirait sur une page de succès à
       * laquelle elle n'a plus rien à voir. */
      clearCheckoutIntent()
      if (lockedSignalKey !== null) saveCheckoutIntent(lockedSignalKey)
      // La destination vient du backend, jamais d'une URL construite ici.
      window.location.assign(session.checkout_url)
    } catch (caught) {
      setActionError(caught)
      setChoosing(null)
      busyRef.current = false
    }
  }

  async function openPortal() {
    setActionError(null)
    setOpeningPortal(true)
    try {
      const session = await billing.portal()
      window.location.assign(session.portal_url)
    } catch (caught) {
      setActionError(caught)
      setOpeningPortal(false)
    }
  }

  if (loading) {
    return (
      <div className={styles.page}>
        <SectionHeading title={t.billing.title} lead={t.billing.lead} level={1} />
        <Card padding="lg">
          <Skeleton width="45%" height="1.5rem" />
        </Card>
      </div>
    )
  }

  if (error || !catalogue || !status) {
    const copy = describeError(error, t)
    return (
      <div className={styles.page}>
        <SectionHeading title={t.billing.title} lead={t.billing.lead} level={1} />
        <Callout tone="danger" title={copy.title} live>
          {copy.body}
        </Callout>
      </div>
    )
  }

  const action = status.billing_action
  const isPaid = status.plan_code !== 'discovery'
  /* P0-03G — l'échéance de résiliation, telle que le SERVEUR la donne. Aucun
     calcul, aucune comparaison à l'horloge locale : une échéance déjà passée
     ne retire aucun droit tant que Stripe n'a pas changé le statut. */
  const scheduledEnd = status.scheduled_cancellation_at
  const actionCopy = actionError ? describeError(actionError, t) : null
  const expiresAt =
    actionError instanceof ApiError && typeof actionError.extra.expires_at === 'string'
      ? date(actionError.extra.expires_at)
      : null

  return (
    <div className={styles.page}>
      <SectionHeading title={t.billing.title} lead={t.billing.lead} level={1} />

      {/* Les DROITS actuels — `plan_code` et le statut brut, affichés, jamais
          interprétés pour décider d'une action. */}
      <Card padding="lg" as="section" className={styles.statusCard}>
        <div className={styles.statusHead}>
          <div>
            <p className={styles.statusLabel}>{t.billing.currentPlan}</p>
            <p className={styles.statusPlan}>{t.billing.plans[status.plan_code]}</p>
          </div>
          <Badge tone={isPaid ? 'positive' : 'neutral'}>
            {/* Un statut que Stripe inventerait n'est pas montré au client :
                `billing_action` a déjà décidé de le traiter comme une
                vérification, et afficher le terme technique contredirait ce
                défaut fermé. */}
            {t.billing.status[
              (status.subscription_status ?? 'none') as keyof typeof t.billing.status
            ] ?? t.billing.status.unknown}
          </Badge>
        </div>

        {/* La date de période n'est une PROMESSE que si l'abonnement est
            réellement géré. Un abonnement résilié ou impayé garde une
            `current_period_end` — c'est la fin de ce qui a été payé, pas un
            renouvellement à venir. L'annoncer sur un écran qui propose de
            choisir une offre dirait au client qu'il est encore abonné. */}
        {action === 'manage_subscription' && status.current_period_end && !scheduledEnd ? (
          <p className={styles.statusLine}>
            {interpolate(t.billing.renewsOn, { date: date(status.current_period_end) ?? '' })}
          </p>
        ) : null}

        {/* P0-03G — la date vient du SERVEUR, et d'un seul champ.
            `current_period_end` ne la remplace jamais : Stripe permet de
            planifier une résiliation à une autre date, et emprunter la fin de
            période annoncerait alors une échéance qui n'est pas la sienne.

            Même règle que la ligne de période : une résiliation programmée dit
            que l'accès court ENCORE jusqu'à une date. Le dire à un compte dont
            l'accès est SUSPENDU mettrait deux affirmations contradictoires sur
            le même écran. */}
        {action === 'manage_subscription' && scheduledEnd ? (
          <Callout tone="warning" title={t.billing.cancellationTitle}>
            {interpolate(
              status.cancel_at_period_end
                ? t.billing.cancellationAtPeriodEnd
                : t.billing.cancellationOnDate,
              { date: date(scheduledEnd) ?? '' },
            )}
          </Callout>
        ) : null}

        {action === 'manage_subscription' ? (
          <div className={styles.portal}>
            <p className={styles.statusLine}>{t.billing.manageLead}</p>
            <Button variant="secondary" loading={openingPortal} onClick={() => void openPortal()}>
              {t.billing.managePortal}
            </Button>
          </div>
        ) : null}
      </Card>

      {actionCopy ? (
        <Callout tone="danger" title={actionCopy.title} live>
          {actionCopy.body}
          {expiresAt ? (
            <> {interpolate(t.billing.errors.checkoutInProgressExpiry, { date: expiresAt })}</>
          ) : null}
        </Callout>
      ) : null}

      {/* L'abonnement existe encore et l'accès est suspendu. Aucun second
          paiement : le backend le refuserait, et le proposer laisserait croire
          qu'acheter à nouveau réglerait l'incident. */}
      {action === 'recover_payment' ? (
        <Callout
          tone="warning"
          title={t.billing.recoverTitle}
          action={
            <Button loading={openingPortal} onClick={() => void openPortal()}>
              {t.billing.recoverCta}
            </Button>
          }
        >
          {t.billing.recoverBody}
        </Callout>
      ) : null}

      {/* Ni achat, ni portail présenté comme une solution certaine : personne ne
          sait encore ce que porte ce compte. Une vérification humaine d'abord. */}
      {action === 'contact_support' ? (
        <Callout
          tone="warning"
          title={t.billing.supportTitle}
          action={
            <a className={styles.supportLink} href={`mailto:${t.billing.supportEmail}`}>
              {t.billing.supportCta}
            </a>
          }
        >
          {t.billing.supportBody}
        </Callout>
      ) : null}

      {action === 'choose_plan' ? (
        <>
          {/* Une tentative expirée porte encore un `payment_issue`, mais
              l'incident n'est plus « en cours » : la place est libre, et le
              dire autrement retiendrait un client qui peut recommencer. */}
          {status.payment_issue ? (
            <Callout tone="info">{t.billing.terminalNotice}</Callout>
          ) : null}

          <fieldset className={styles.currency}>
            <legend className={styles.currencyLegend}>{t.billing.currency}</legend>
            <p className={styles.currencyHelp}>{t.billing.currencyLead}</p>
            <div className={styles.currencyOptions}>
              {catalogue.currencies.map((code) => (
                <label
                  key={code}
                  className={`${styles.currencyOption} ${
                    currency === code ? styles.currencySelected : ''
                  }`}
                >
                  <input
                    type="radio"
                    name="kivou-currency"
                    className={styles.radio}
                    value={code}
                    checked={currency === code}
                    onChange={() => setCurrency(code)}
                  />
                  {code.toUpperCase()}
                </label>
              ))}
            </div>
          </fieldset>

          <section aria-label={t.billing.plansTitle}>
            <PlanGrid
              catalogue={catalogue}
              variant="app"
              currency={currency}
              currentPlan={status.plan_code}
              onChoose={(plan) => void startCheckout(plan)}
              choosingPlan={choosing}
              disabled={choosing !== null}
            />
          </section>
        </>
      ) : null}
    </div>
  )
}
