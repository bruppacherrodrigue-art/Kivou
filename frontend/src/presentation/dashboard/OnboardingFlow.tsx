import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Check, Info, Target } from 'lucide-react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { MVP_THRESHOLD_CURRENCIES } from '../../api/capabilities'
import { icps } from '../../api/endpoints'
import { describeError } from '../../api/errorCopy'
import type { TargetIcp } from '../../api/types'
import { useSession } from '../../auth/SessionProvider'
import { planFromSearch, planSearch } from '../../billing/planRoute'
import { useI18n, withRenderableSpaces } from '../../i18n'
import { AuthShell } from './AuthShell'
import {
  UnknownTargetingToken,
  toTargetIcpPayload,
  type ReferenceTargetingDraft,
  type TargetingField,
} from './targetingInput'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Progress } from './ui/progress'
import { Textarea } from './ui/textarea'
import { useResource } from './resources'

const initialDraft: ReferenceTargetingDraft = {
  name: '',
  offer: '',
  precision: '',
  companies: '',
  territory: '',
  terms: '',
  minAmount: '',
  currency: 'CHF',
}

const steps = [
  { label: 'Votre offre', help: 'Ce que vous proposez réellement' },
  { label: 'Votre marché', help: 'À qui et où vous pouvez vendre' },
  { label: 'Seuil essentiel', help: 'Nommer le profil et poser un minimum' },
  { label: 'Vérification', help: 'Relire avant d’examiner les signaux' },
] as const

type LocalField = TargetingField | 'offer' | 'name' | 'market' | 'general'

interface VisibleError {
  field: LocalField
  message: string
}

interface AccountOnboardingWork {
  creation: Promise<TargetIcp>
  reconciliation: Promise<void> | null
}

interface CreatedTarget {
  accountId: string
  target: TargetIcp
}

interface OnboardingOperation {
  id: number
  accountId: string
  generation: number
}

const onboardingWorkByAccount = new Map<string, AccountOnboardingWork>()

function createTargetOnce(
  accountId: string,
  payload: ReturnType<typeof toTargetIcpPayload>,
): Promise<TargetIcp> {
  const existing = onboardingWorkByAccount.get(accountId)
  if (existing) return existing.creation

  const creation = icps.create(payload)
  const work: AccountOnboardingWork = { creation, reconciliation: null }
  onboardingWorkByAccount.set(accountId, work)
  void creation.catch(() => {
    if (onboardingWorkByAccount.get(accountId) === work) {
      onboardingWorkByAccount.delete(accountId)
    }
  })
  return creation
}

function reconcileTargetOnce(accountId: string, refresh: () => Promise<void>): Promise<void> {
  const work = onboardingWorkByAccount.get(accountId)
  if (!work) return refresh()
  if (work.reconciliation) return work.reconciliation

  const reconciliation = refresh().then(
    () => {
      if (onboardingWorkByAccount.get(accountId) === work) {
        onboardingWorkByAccount.delete(accountId)
      }
    },
    (error: unknown) => {
      if (onboardingWorkByAccount.get(accountId) === work) {
        work.reconciliation = null
      }
      throw error
    },
  )
  work.reconciliation = reconciliation
  return reconciliation
}

function mappingError(error: UnknownTargetingToken): VisibleError {
  const copy: Record<TargetingField, string> = {
    offers: `« ${error.token} » ne correspond à aucun type d’offre proposé. Utilisez un libellé affiché par Kivou ou son code exact.`,
    buyer_trades: `« ${error.token} » ne correspond à aucun corps de métier proposé. Utilisez un libellé affiché par Kivou ou son code exact.`,
    territories: `« ${error.token} » ne correspond à aucun territoire couvert. Utilisez un pays affiché par Kivou ou son code exact.`,
    threshold: 'Indiquez un montant positif ou nul dans une devise proposée.',
  }
  return { field: error.field, message: copy[error.field] }
}

function fieldStep(field: LocalField): number {
  if (field === 'offer') return 0
  if (field === 'offers' || field === 'buyer_trades' || field === 'territories' || field === 'market') return 1
  if (field === 'threshold' || field === 'name') return 2
  return 3
}

export function OnboardingFlow() {
  const { state: session } = useSession()
  const loadProfiles = useCallback(() => icps.list(), [])
  const profiles = useResource(loadProfiles)
  const provisional = session.status === 'authenticated'
    && session.me.onboarding_status !== 'ready_for_signals'
    ? profiles.data?.find((profile) => profile.provisional)
    : undefined

  if (profiles.loading && !profiles.data) {
    return <AuthShell eyebrow="Première configuration" title="Votre profil cible" description="Chargement…" showBrand={false}><p role="status">Chargement…</p></AuthShell>
  }
  if (provisional) return <ProvisionalOnboarding profile={provisional} />
  return <LegacyOnboardingFlow />
}

function ProvisionalOnboarding({ profile }: { profile: TargetIcp }) {
  const navigate = useNavigate()
  const { refresh } = useSession()
  const loadOptions = useCallback(() => icps.options(), [])
  const options = useResource(loadOptions)
  const [zones, setZones] = useState<string[]>(
    ((profile.customer_input.territory_subdivisions?.length ?? 0) > 0
      ? profile.customer_input.territory_subdivisions ?? []
      : profile.customer_input.territories),
  )
  const [sectorPrefix, setSectorPrefix] = useState(profile.customer_input.sector_cpv_prefixes?.[0] ?? '')
  const [offer, setOffer] = useState(profile.customer_input.offer_summary)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(false)

  const confirm = async () => {
    const zoneCodes = zones
    const territories = [...new Set(zoneCodes.map((zone) => zone.split('-', 1)[0]))]
    const territorySubdivisions = zoneCodes.filter((zone) => zone.includes('-'))
    if (!zoneCodes.length || !sectorPrefix || !offer.trim()) return setError(true)
    setSubmitting(true)
    setError(false)
    try {
      await icps.update(profile.target_icp_id, {
        label: options.data?.sectors.find((item) => item.prefix === sectorPrefix)?.label || profile.label,
        customer_input: {
          ...profile.customer_input,
          offer_summary: offer.trim(),
          territories,
          territory_subdivisions: territorySubdivisions,
          sector_cpv_prefixes: sectorPrefix ? [sectorPrefix] : [],
        },
      })
      await refresh()
      navigate('/app', { replace: true, state: { firstSignals: true } })
    } catch {
      setError(true)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthShell eyebrow="Profil provisoire" title="Confirmez votre profil cible" description="Trois réponses suffisent pour recevoir vos signaux." wide showBrand={false} navigationDisabled={submitting}>
      <section className="onboarding-step">
        <div className="onboarding-form-grid">
          <div className="form-field form-field-wide"><label htmlFor="onboarding-zone">Zone</label><select id="onboarding-zone" multiple value={zones} onChange={(event) => setZones(Array.from(event.currentTarget.selectedOptions, (option) => option.value))}>{options.data?.zones.map((zone) => <option key={zone.code} value={zone.code}>{zone.label} ({zone.code})</option>)}</select><p className="field-hint">Sélectionnez un ou plusieurs départements ou cantons.</p></div>
          <div className="form-field form-field-wide"><label htmlFor="onboarding-sector">Secteur</label><select id="onboarding-sector" value={sectorPrefix} onChange={(event) => setSectorPrefix(event.target.value)}><option value="">Sélectionner un secteur</option>{options.data?.sectors.map((sector) => <option key={sector.prefix} value={sector.prefix}>{sector.label}</option>)}</select></div>
          <div className="form-field form-field-wide"><label htmlFor="onboarding-offer">Ce que vous vendez</label><Textarea id="onboarding-offer" value={offer} onChange={(event) => setOffer(event.target.value)} /></div>
        </div>
      </section>
      {options.loading && !options.data ? <p role="status">Chargement des zones et secteurs…</p> : null}
      {error || options.error ? <p className="form-error" role="alert">Vérifiez les trois champs puis réessayez.</p> : null}
      <div className="onboarding-actions"><span /><Button type="button" className="primary-action" disabled={submitting} onClick={() => void confirm()}>Recevoir mes signaux</Button></div>
    </AuthShell>
  )
}

function LegacyOnboardingFlow() {
  const { t } = useI18n()
  const location = useLocation()
  const navigate = useNavigate()
  const { state: session, refresh } = useSession()
  const selectedPlan = planFromSearch(location.search)
  const currentAccountId = session.status === 'authenticated' ? session.me.account_id : null

  const [step, setStep] = useState(0)
  const [draft, setDraft] = useState<ReferenceTargetingDraft>(initialDraft)
  const [error, setError] = useState<VisibleError | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [pendingNavigation, setPendingNavigation] = useState<OnboardingOperation | null>(null)
  const createdRef = useRef<CreatedTarget | null>(null)
  const busyRef = useRef(false)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const navigatedRef = useRef(false)
  const mountedRef = useRef(false)
  const generationRef = useRef(0)
  const operationIdRef = useRef(0)
  const activeOperationRef = useRef<OnboardingOperation | null>(null)
  const currentAccountRef = useRef(currentAccountId)
  currentAccountRef.current = currentAccountId

  const terms = useMemo(
    () => [...new Set(draft.terms.split(',').map((term) => term.trim()).filter(Boolean))],
    [draft.terms],
  )

  useEffect(() => {
    if (navigatedRef.current) headingRef.current?.focus()
  }, [step])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      generationRef.current += 1
    }
  }, [])

  useEffect(() => {
    setError(null)
  }, [location.search])

  useLayoutEffect(() => {
    generationRef.current += 1
    activeOperationRef.current = null
    busyRef.current = false
    if (createdRef.current?.accountId !== currentAccountId) createdRef.current = null
    navigatedRef.current = false
    setDraft(initialDraft)
    setStep(0)
    setSubmitting(false)
    setError(null)
    setPendingNavigation(null)
  }, [currentAccountId])

  const requestIsCurrent = (operation: OnboardingOperation) =>
    mountedRef.current &&
    currentAccountRef.current === operation.accountId &&
    generationRef.current === operation.generation &&
    activeOperationRef.current?.id === operation.id

  useEffect(() => {
    if (!pendingNavigation) return
    setPendingNavigation(null)
    if (
      !mountedRef.current ||
      currentAccountRef.current !== pendingNavigation.accountId ||
      generationRef.current !== pendingNavigation.generation
    ) {
      return
    }
    const destination =
      selectedPlan === 'discovery'
        ? '/app/signals'
        : `/checkout${planSearch(selectedPlan)}`
    navigate(destination, { replace: true, state: { activationCompleted: true } })
  }, [navigate, pendingNavigation, selectedPlan])

  function update(field: keyof ReferenceTargetingDraft, value: string) {
    setDraft((current) => ({ ...current, [field]: value }))
    setError(null)
  }

  function go(nextStep: number) {
    navigatedRef.current = true
    setError(null)
    setStep(nextStep)
  }

  function next() {
    if (step === 0 && !draft.offer.trim()) {
      setError({ field: 'offer', message: 'Décrivez ce que vous proposez pour continuer.' })
      return
    }
    if (step === 1 && (!draft.companies.trim() || !draft.territory.trim() || terms.length === 0)) {
      setError({
        field: 'market',
        message: 'Indiquez les entreprises, le territoire et au moins un mot-clé.',
      })
      return
    }
    if (
      step === 2 &&
      (!draft.name.trim() ||
        !draft.minAmount.trim() ||
        !Number.isFinite(Number(draft.minAmount)) ||
        Number(draft.minAmount) < 0 ||
        !MVP_THRESHOLD_CURRENCIES.includes(draft.currency))
    ) {
      setError({
        field: !draft.name.trim() ? 'name' : 'threshold',
        message: 'Nommez le profil et indiquez un montant minimum valide.',
      })
      return
    }
    go(Math.min(step + 1, steps.length - 1))
  }

  async function finish() {
    if (busyRef.current) return
    if (session.status !== 'authenticated') return
    const accountId = session.me.account_id

    let payload: ReturnType<typeof toTargetIcpPayload>
    try {
      payload = toTargetIcpPayload(draft, t)
    } catch (caught) {
      if (caught instanceof UnknownTargetingToken) {
        const visible = mappingError(caught)
        setError(visible)
        goToInvalidField(visible.field)
        return
      }
      throw caught
    }

    busyRef.current = true
    const operation: OnboardingOperation = {
      id: ++operationIdRef.current,
      accountId,
      generation: ++generationRef.current,
    }
    activeOperationRef.current = operation
    setSubmitting(true)
    setError(null)
    try {
      if (createdRef.current?.accountId !== accountId) {
        const created = await createTargetOnce(accountId, payload)
        if (requestIsCurrent(operation)) {
          createdRef.current = { accountId, target: created }
        }
      }
      await reconcileTargetOnce(accountId, refresh)
      if (!requestIsCurrent(operation)) return
      setPendingNavigation(operation)
    } catch (caught) {
      if (!requestIsCurrent(operation)) return
      if (createdRef.current?.accountId === accountId) {
        setError({
          field: 'general',
          message: 'Votre profil cible a bien été enregistré, mais Kivou n’a pas pu finaliser l’ouverture de votre compte. Réessayez sans recréer le profil.',
        })
      } else {
        const copy = describeError(caught, t)
        setError({ field: 'general', message: `${copy.title} ${copy.body}`.trim() })
      }
    } finally {
      if (activeOperationRef.current?.id === operation.id) {
        activeOperationRef.current = null
        busyRef.current = false
        if (mountedRef.current) setSubmitting(false)
      }
    }
  }

  function goToInvalidField(field: LocalField) {
    const nextStep = fieldStep(field)
    if (nextStep !== step) {
      navigatedRef.current = true
      setStep(nextStep)
    }
  }

  const alreadyReady =
    session.status === 'authenticated' &&
    session.me.onboarding_status === 'ready_for_signals' &&
    createdRef.current?.accountId !== currentAccountId
  if (alreadyReady) return <Navigate to="/app/signals" replace />

  const inlineError = (field: LocalField | LocalField[]) => {
    const accepted = Array.isArray(field) ? field : [field]
    return error && accepted.includes(error.field) ? (
      <p className="form-error" role="alert">{error.message}</p>
    ) : null
  }

  return (
    <AuthShell
      eyebrow="Première configuration"
      title="Définir ce que Kivou doit surveiller"
      description="Quatre étapes courtes suffisent pour expliquer votre offre, votre marché et le seuil utile."
      wide
      showBrand={false}
      navigationDisabled={submitting}
    >
      <div className="onboarding-progress" aria-label={`Étape ${step + 1} sur ${steps.length}`}>
        <div><span>Étape {step + 1} sur {steps.length}</span><strong>{steps[step].label}</strong></div>
        <Progress value={((step + 1) / steps.length) * 100} />
      </div>

      <div className="prototype-notice" role="note">
        <Info aria-hidden="true" />
        <p>Le profil cible sera enregistré dans votre compte Kivou. Les catégories inconnues sont refusées plutôt que devinées.</p>
      </div>

      {step === 0 ? (
        <section className="onboarding-step" aria-labelledby="onboarding-offer-title">
          <div className="onboarding-step-heading">
            <span><Target aria-hidden="true" /></span>
            <div><h2 id="onboarding-offer-title" ref={headingRef} tabIndex={-1}>Que vendez-vous ?</h2><p>Utilisez les mots qu’un client emploierait pour décrire votre offre.</p></div>
          </div>
          <div className="onboarding-form-grid">
            <div className="form-field form-field-wide">
              <label htmlFor="onboarding-offer">Produits et services proposés</label>
              <Textarea id="onboarding-offer" placeholder="Ex. Portes, huisseries, quincaillerie et composants d’agencement" value={draft.offer} aria-invalid={error?.field === 'offer' || undefined} onChange={(event) => update('offer', event.target.value)} />
              <p className="field-hint">Restez concret : une phrase suffit.</p>
              {inlineError('offer')}
            </div>
            <div className="form-field form-field-wide">
              <label htmlFor="onboarding-summary">Précision utile <span>(facultatif)</span></label>
              <Textarea id="onboarding-summary" placeholder="Ex. Nous fournissons des séries sur mesure avec livraison en Bavière." value={draft.precision} onChange={(event) => update('precision', event.target.value)} />
            </div>
          </div>
        </section>
      ) : null}

      {step === 1 ? (
        <section className="onboarding-step" aria-labelledby="onboarding-market-title">
          <div className="onboarding-step-heading">
            <span>2</span>
            <div><h2 id="onboarding-market-title" ref={headingRef} tabIndex={-1}>Quel marché recherchez-vous ?</h2><p>Décrivez les entreprises capables d’acheter votre offre et la zone que vous couvrez.</p></div>
          </div>
          <div className="onboarding-form-grid">
            <div className="form-field form-field-wide">
              <label htmlFor="onboarding-companies">Entreprises recherchées</label>
              <Textarea id="onboarding-companies" placeholder="Ex. Routes et génie civil" value={draft.companies} aria-invalid={error?.field === 'buyer_trades' || error?.field === 'market' || undefined} onChange={(event) => update('companies', event.target.value)} />
              {inlineError('buyer_trades')}
            </div>
            <div className="form-field">
              <label htmlFor="onboarding-territory">Territoire couvert</label>
              <Input id="onboarding-territory" placeholder="Ex. France, Allemagne" value={draft.territory} aria-invalid={error?.field === 'territories' || error?.field === 'market' || undefined} onChange={(event) => update('territory', event.target.value)} />
              {inlineError('territories')}
            </div>
            <div className="form-field">
              <label htmlFor="onboarding-terms">Mots-clés à surveiller</label>
              <Input id="onboarding-terms" placeholder="Ex. Matériaux et composants" value={draft.terms} aria-invalid={error?.field === 'offers' || error?.field === 'market' || undefined} onChange={(event) => update('terms', event.target.value)} />
              <p className="field-hint">Séparez les termes par des virgules.</p>
              {inlineError('offers')}
            </div>
          </div>
          {inlineError('market')}
        </section>
      ) : null}

      {step === 2 ? (
        <section className="onboarding-step" aria-labelledby="onboarding-threshold-title">
          <div className="onboarding-step-heading">
            <span>3</span>
            <div><h2 id="onboarding-threshold-title" ref={headingRef} tabIndex={-1}>Quel seuil mérite votre attention ?</h2><p>Un seul minimum suffit pour éviter de remonter des marchés trop petits pour votre activité.</p></div>
          </div>
          <div className="onboarding-form-grid">
            <div className="form-field form-field-wide">
              <label htmlFor="onboarding-name">Nom du profil</label>
              <Input id="onboarding-name" placeholder="Ex. Menuiserie intérieure · Bavière" value={draft.name} aria-invalid={error?.field === 'name' || undefined} onChange={(event) => update('name', event.target.value)} />
              {inlineError('name')}
            </div>
            <div className="form-field">
              <label htmlFor="onboarding-min-amount">Montant minimum du marché</label>
              <Input id="onboarding-min-amount" type="number" min="0" step="1000" placeholder="Ex. 250000" value={draft.minAmount} aria-invalid={error?.field === 'threshold' || undefined} onChange={(event) => update('minAmount', event.target.value)} />
            </div>
            <div className="form-field">
              <label htmlFor="onboarding-currency">Devise</label>
              <select id="onboarding-currency" className="lifecycle-select" value={draft.currency} aria-invalid={error?.field === 'threshold' || undefined} onChange={(event) => update('currency', event.target.value)}>
                <option value="CHF">CHF</option>
                <option value="EUR">EUR</option>
              </select>
              <p className="field-hint">Le seuil porte sur la valeur publique du marché, pas sur un budget fournisseur disponible.</p>
            </div>
          </div>
          {inlineError('threshold')}
        </section>
      ) : null}

      {step === 3 ? (
        <section className="onboarding-step" aria-labelledby="onboarding-review-title">
          <div className="onboarding-step-heading">
            <span><Check aria-hidden="true" /></span>
            <div><h2 id="onboarding-review-title" ref={headingRef} tabIndex={-1}>Vérifier le profil cible</h2><p>Kivou utilisera cette définition pour sélectionner des marchés attribués à examiner, pas pour affirmer qu’un achat est ouvert.</p></div>
          </div>
          <dl className="onboarding-review">
            <div><dt>Profil</dt><dd>{draft.name}</dd></div>
            <div><dt>Offre</dt><dd>{draft.offer}</dd></div>
            {draft.precision ? <div><dt>Précision</dt><dd>{draft.precision}</dd></div> : null}
            <div><dt>Entreprises</dt><dd>{draft.companies}</dd></div>
            <div><dt>Territoire</dt><dd>{draft.territory}</dd></div>
            <div><dt>Mots-clés</dt><dd>{terms.join(' · ')}</dd></div>
            <div><dt>Seuil</dt><dd>{withRenderableSpaces(Number(draft.minAmount).toLocaleString('fr-CH'))} {draft.currency}</dd></div>
          </dl>
        </section>
      ) : null}

      {inlineError('general')}

      <div className="onboarding-actions">
        {step > 0 ? (
          <Button type="button" variant="outline" className="secondary-action" disabled={submitting} onClick={() => go(step - 1)}>
            <ArrowLeft aria-hidden="true" /> Retour
          </Button>
        ) : <span />}
        {step < steps.length - 1 ? (
          <Button type="button" className="primary-action" onClick={next}>Continuer <ArrowRight aria-hidden="true" /></Button>
        ) : (
          <Button type="button" className="primary-action" disabled={submitting} onClick={() => void finish()}>
            {createdRef.current?.accountId === currentAccountId ? 'Finaliser et voir mes signaux' : 'Enregistrer et voir les signaux'} <ArrowRight aria-hidden="true" />
          </Button>
        )}
      </div>
    </AuthShell>
  )
}
