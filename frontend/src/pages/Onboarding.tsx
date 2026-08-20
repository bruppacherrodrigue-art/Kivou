import { useEffect, useRef, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useI18n } from '../i18n'
import { useSession } from '../auth/SessionProvider'
import { Card, Callout, DataList, DataRow, SectionHeading } from '../components/Surfaces'
import { Button } from '../components/Button'
import { SignalDetectedIllustration } from '../assets/Illustrations'
import { ActivationProgress } from '../activation/ActivationProgress'
import { CompletenessNotice, IcpFields, emptyIcpValue, missingFields } from './IcpForm'
import type { IcpFieldSection, IcpFormValue } from './IcpForm'
import { MVP_TERRITORIES, territoryLabel } from '../api/capabilities'
import { icps } from '../api/endpoints'
import { describeError } from '../api/errorCopy'
import type { TargetIcp } from '../api/types'
import styles from './Onboarding.module.css'

/* L'onboarding.
 *
 * Les cinq questions sont posées en trois temps plutôt qu'en une page — non
 * pour découper le formulaire, mais parce que chaque temps répond à une
 * question que le client se pose déjà : ce que je vends, à qui et où, à partir
 * de quel montant. Une quatrième vue relit le tout dans ses mots avant
 * d'engager quoi que ce soit.
 *
 * Les champs restent ceux de `IcpFields`, et c'est délibéré : `/app/icps` et
 * l'onboarding posent LES MÊMES questions, et deux implémentations en
 * divergeraient au premier ajout d'option.
 *
 * Aucun `account_id` n'est envoyé : la propriété vient de la session.
 */

type StepKey = 'offer' | 'audience' | 'threshold' | 'review'

const STEPS: readonly StepKey[] = ['offer', 'audience', 'threshold', 'review'] as const

/* Les groupes de champs par étape, ET leur ordre.
 *
 * Le nom du profil accompagne le seuil plutôt que d'ouvrir le parcours : c'est
 * une question d'intendance — comment le client s'y retrouvera s'il en crée
 * plusieurs — et la poser en premier ferait commencer la mise en route par la
 * seule question qui ne parle pas de son métier.
 *
 * `secondary_offers` et `secondary_buyer_trades` existent dans le contrat mais
 * ne sont collectés nulle part aujourd'hui ; l'onboarding ne les invente pas.
 */
const SECTIONS: Record<StepKey, readonly IcpFieldSection[]> = {
  offer: ['offers', 'summary'],
  audience: ['trades', 'territories'],
  threshold: ['threshold', 'label'],
  /* La relecture n'affiche aucun champ — mais `IcpFields` reste monté.
   * Le démonter effacerait la saisie brute du seuil (une devise choisie avant
   * le montant, un montant en cours de frappe), et un Retour depuis la
   * relecture rendrait au client un formulaire qu'il croyait rempli. */
  review: [],
}

/** Ce qui manque à CETTE étape. La règle reste celle de `missingFields` :
 *  une seconde règle parallèle finirait par contredire la première. */
function missingForStep(step: StepKey, value: IcpFormValue): string[] {
  const missing = missingFields(value)
  const labelMissing = value.label.trim().length === 0 ? ['label'] : []

  switch (step) {
    case 'offer':
      return missing.filter((field) => field === 'offers')
    case 'audience':
      return missing.filter((field) => field === 'territories' || field === 'buyer_trades')
    case 'threshold':
      return [...missing.filter((field) => field === 'minimum_contract_value'), ...labelMissing]
    case 'review':
      return [...missing, ...labelMissing]
  }
}

export function Onboarding() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const { state: session, refresh } = useSession()

  const [value, setValue] = useState<IcpFormValue>(emptyIcpValue())
  const [stepIndex, setStepIndex] = useState(0)
  const [showMissing, setShowMissing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)

  /* Le ciblage DÉJÀ enregistré par le serveur.
   *
   * Le backend crée un profil à chaque `POST /target-icps` et ne déduplique
   * rien par contenu : deux envois font deux profils. Or la séquence de
   * finalisation — créer, puis relire la session, puis naviguer — peut échouer
   * APRÈS la création. Sans mémoire de ce qui a déjà réussi, le bouton
   * « Réessayer » créerait un second ciblage identique, que le client n'a
   * jamais demandé et qu'aucun écran ne permet de supprimer.
   *
   * Une ref, et non un état : le verrou doit être posé dans le même tour de
   * boucle que l'appel, sans attendre un rendu. */
  const createdRef = useRef<TargetIcp | null>(null)
  /** Anti double-envoi : deux clics rapprochés ne doivent produire qu'un appel. */
  const busyRef = useRef(false)
  const headingRef = useRef<HTMLHeadingElement>(null)
  /** Le premier rendu ne vole pas le focus ; les changements d'étape, si. */
  const navigatedRef = useRef(false)

  const step = STEPS[stepIndex]
  const stepMissing = missingForStep(step, value)
  const missing = missingFields(value)

  useEffect(() => {
    if (!navigatedRef.current) return
    headingRef.current?.focus()
  }, [stepIndex])

  function goTo(nextIndex: number) {
    navigatedRef.current = true
    setShowMissing(false)
    setStepIndex(nextIndex)
  }

  function goNext() {
    // Le bouton reste utilisable : bloquer sans rien dire laisse le client
    // chercher ce qu'il aurait mal fait (§13).
    if (stepMissing.length > 0) {
      setShowMissing(true)
      return
    }
    goTo(stepIndex + 1)
  }

  /* Créer puis finaliser — deux moments, un seul verrou.
   *
   * Le `POST` n'est rejoué que s'il n'a jamais abouti. Tout le reste — relire
   * la session, puis rejoindre le feed — est rejouable autant de fois que
   * nécessaire. */
  async function submit() {
    if (busyRef.current) return
    if (stepMissing.length > 0) {
      setShowMissing(true)
      return
    }

    busyRef.current = true
    setSubmitting(true)
    setError(null)
    try {
      if (createdRef.current === null) {
        createdRef.current = await icps.create({
          label: value.label.trim(),
          customer_input: value.input,
        })
      }
      // Le statut d'onboarding est RECALCULÉ côté serveur : le relire est la
      // seule façon d'en connaître la valeur réelle.
      await refresh()
      navigate('/app/signals', { replace: true, state: { activationCompleted: true } })
    } catch (caught) {
      setError(caught)
    } finally {
      busyRef.current = false
      setSubmitting(false)
    }
  }

  /* Un onboarding déjà terminé n'a pas de formulaire.
   *
   * Le cas visé n'est pas le client qui reviendrait par curiosité : c'est le
   * remontage qui suit un incident. Le ciblage a été enregistré, la session
   * n'a pas pu être relue, la page est rechargée — et `/me` répond alors
   * `ready_for_signals`. Sans cette garde, l'écran rouvrirait un formulaire
   * vierge et le client créerait un second profil.
   *
   * `createdRef` exempte le montage courant : c'est LUI qui vient de créer le
   * ciblage, et il doit pouvoir rejoindre le feed avec son moment d'activation
   * plutôt que d'être redirigé sans rien dire. */
  const alreadyReady =
    session.status === 'authenticated' && session.me.onboarding_status === 'ready_for_signals'
  if (alreadyReady && createdRef.current === null) {
    return <Navigate to="/app/signals" replace />
  }

  const created = createdRef.current !== null
  const errorCopy = error && !created ? describeError(error, t) : null
  const stepTitle: Record<StepKey, string> = {
    offer: t.onboarding.stepOfferTitle,
    audience: t.onboarding.stepAudienceTitle,
    threshold: t.onboarding.stepThresholdTitle,
    review: t.onboarding.reviewTitle,
  }

  return (
    <main className={styles.page} id="kivou-main">
      <div className={styles.inner}>
        <header className={styles.header}>
          <SignalDetectedIllustration className={styles.illustration} />
          <SectionHeading
            eyebrow={t.onboarding.welcomeTitle}
            title={t.onboarding.title}
            lead={t.onboarding.lead}
            level={1}
          />
          <ActivationProgress current="targeting" />
        </header>

        {/* Le ciblage a été enregistré, mais l'ouverture des signaux n'a pas
            abouti. Dire « la création a échoué » serait faux, et pousserait le
            client à recommencer une saisie qui existe déjà côté serveur. */}
        {error && created ? (
          <Callout
            tone="warning"
            title={t.onboarding.savedNotFinalisedTitle}
            live
            action={
              <Button loading={submitting} onClick={() => void submit()}>
                {t.onboarding.finaliseRetry}
              </Button>
            }
          >
            {t.onboarding.savedNotFinalisedBody}
          </Callout>
        ) : null}

        {errorCopy ? (
          <Callout tone="danger" title={errorCopy.title} live>
            {errorCopy.body}
          </Callout>
        ) : null}

        <Card padding="lg" as="section">
          <div className={styles.step}>
            <h2 className={styles.stepTitle} ref={headingRef} tabIndex={-1}>
              {stepTitle[step]}
            </h2>
            {step === 'review' ? (
              <p className={styles.stepLead}>{t.onboarding.reviewLead}</p>
            ) : null}

            <IcpFields
              value={value}
              onChange={setValue}
              error={error}
              sections={SECTIONS[step]}
            />

            {step === 'review' ? <TargetingSummary value={value} /> : null}
          </div>
        </Card>

        {showMissing && stepMissing.length > 0 ? (
          <Callout tone="warning" title={t.onboarding.stepIncomplete} live>
            <span>{t.onboarding.missingTitle} </span>
            {stepMissing
              .map(
                (field) =>
                  t.onboarding.missing[field as keyof typeof t.onboarding.missing] ?? field,
              )
              .join(', ')}
          </Callout>
        ) : null}

        <div className={styles.footer}>
          {step === 'review' ? <CompletenessNotice missing={missing} /> : null}

          <div className={styles.actions}>
            {stepIndex > 0 ? (
              <Button
                variant="secondary"
                size="lg"
                disabled={submitting}
                onClick={() => goTo(stepIndex - 1)}
              >
                {t.common.back}
              </Button>
            ) : null}

            {step === 'review' ? (
              <Button size="lg" loading={submitting} onClick={() => void submit()}>
                {t.onboarding.create}
              </Button>
            ) : (
              <Button size="lg" onClick={goNext}>
                {t.common.next}
              </Button>
            )}
          </div>
        </div>
      </div>
    </main>
  )
}

/** La relecture, dans les mots du client : aucun code territoire brut, aucune
 *  clé d'offre, aucun statut moteur. Ce que le client valide ici doit être
 *  reconnaissable pour lui, sinon il valide un texte qu'il ne relit pas. */
function TargetingSummary({ value }: { value: IcpFormValue }) {
  const { t, locale, amount } = useI18n()
  const input = value.input
  const threshold = input.minimum_contract_value

  const territories = input.territories.map((code) => {
    const known = MVP_TERRITORIES.find((territory) => territory.code === code)
    return known ? territoryLabel(known, locale) : code
  })

  return (
    <DataList>
      <DataRow label={t.onboarding.labelField}>
        {value.label.trim() || t.common.notAvailable}
      </DataRow>
      <DataRow label={t.icp.offersLabel}>
        {input.offers.length > 0
          ? input.offers.map((offer) => t.offers[offer]).join(', ')
          : t.common.notAvailable}
      </DataRow>
      <DataRow label={t.icp.tradesLabel}>
        {input.buyer_trades.length > 0
          ? input.buyer_trades.map((trade) => t.trades[trade]).join(', ')
          : t.icp.noTrades}
      </DataRow>
      <DataRow label={t.icp.territoriesLabel}>
        {territories.length > 0 ? territories.join(', ') : t.common.notAvailable}
      </DataRow>
      <DataRow label={t.icp.thresholdLabel} tabular>
        {threshold
          ? (amount(String(threshold.minimum_amount), threshold.currency) ??
            t.common.notAvailable)
          : t.common.notAvailable}
      </DataRow>
      {input.offer_summary.trim() ? (
        <DataRow label={t.onboarding.summaryLabel}>{input.offer_summary.trim()}</DataRow>
      ) : null}
    </DataList>
  )
}
