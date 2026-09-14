import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowRight, Check, X } from 'lucide-react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { icps } from '../api/endpoints'
import { ApiError } from '../api/client'
import { BUYER_TRADES, OFFER_KINDS, type BuyerTrade, type OfferKind, type TargetIcpInput } from '../api/types'
import { useSession } from '../auth/SessionProvider'
import { planFromSearch, planSearch } from '../billing/planRoute'
import { useI18n } from '../i18n'
import { AuthShell } from '../presentation/dashboard/AuthShell'
import { Button } from '../presentation/dashboard/ui/button'
import { Textarea } from '../presentation/dashboard/ui/textarea'
import { useResource } from '../presentation/dashboard/resources'

type FieldErrors = Partial<Record<'zone' | 'sector' | 'offers' | 'offer' | 'trades' | 'general', string>>

// Preserve existing targeting choices: a confirmation must not erase the
// offer categories or amount threshold that make a profile usable.
function toPayload(zones: string[], sector: string, offer: string, offers: OfferKind[], buyerTrades: BuyerTrade[], previous?: TargetIcpInput): TargetIcpInput {
  return {
    ...previous,
    offer_summary: offer.trim(),
    offers,
    secondary_offers: (previous?.secondary_offers ?? []).filter((item) => !offers.includes(item)),
    buyer_trades: buyerTrades,
    secondary_buyer_trades: previous?.secondary_buyer_trades ?? [],
    territories: [...new Set(zones.map((zone) => zone.split('-', 1)[0]))],
    territory_subdivisions: zones.filter((zone) => zone.includes('-')),
    sector_cpv_prefixes: previous?.sector_cpv_prefixes?.[0] === sector ? previous.sector_cpv_prefixes : [sector],
    minimum_contract_value: previous?.minimum_contract_value ?? { currency: 'EUR', minimum_amount: 0, maximum_amount: null },
  }
}

export function ConfirmProfile() {
  const { state: session, refresh } = useSession()
  const { t } = useI18n()
  const navigate = useNavigate()
  const location = useLocation()
  const selectedPlan = planFromSearch(location.search)
  const destination = selectedPlan === 'discovery' ? '/app/signals' : `/app/billing${planSearch(selectedPlan)}`
  const profiles = useResource(useCallback(() => icps.list(), []))
  const options = useResource(useCallback(() => icps.options(), []))
  // A previous failed confirmation may already have changed the provisional
  // profile to a draft. Resume it instead of creating a duplicate.
  const profile = profiles.data?.find((item) => item.provisional)
    ?? profiles.data?.find((item) => item.status === 'draft')
  const [zones, setZones] = useState<string[]>([])
  const [sector, setSector] = useState('')
  const [offer, setOffer] = useState('')
  const [offers, setOffers] = useState<OfferKind[]>([])
  const [buyerTrades, setBuyerTrades] = useState<BuyerTrade[]>([])
  const [hydratedProfile, setHydratedProfile] = useState<string | null>(null)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [submitting, setSubmitting] = useState(false)
  const savedProfileId = useRef<string | null>(null)
  const submissionPending = useRef(false)

  useEffect(() => {
    if (!profile || hydratedProfile === profile.target_icp_id) return
    const input = profile.customer_input
    setZones(input.territory_subdivisions?.length ? input.territory_subdivisions : input.territories)
    setSector(input.sector_cpv_prefixes?.[0] ?? '')
    setOffer(input.offer_summary)
    setOffers(input.offers)
    setBuyerTrades(input.buyer_trades)
    setHydratedProfile(profile.target_icp_id)
  }, [hydratedProfile, profile])

  const sectorLabel = options.data?.sectors.find((item) => item.prefix === sector)?.label
    ?? (profile?.customer_input.sector_cpv_prefixes?.[0] === sector ? profile.label : 'Mon profil cible')
  const customSector = profile && sector && !options.data?.sectors.some((item) => item.prefix === sector)
  const countryLabels: Record<string, string> = { FR: 'France entière', CH: 'Suisse entière' }
  const needsTradeRepair = Boolean(profile?.customer_input.secondary_buyer_trades.length && !profile.customer_input.buyer_trades.length)
  const zoneChoices = [
    ...Array.from(new Set([...Object.keys(countryLabels), ...zones])).filter((code) => !options.data?.zones.some((zone) => zone.code === code))
      .map((code) => ({ value: code, label: countryLabels[code] ?? code })),
    ...(options.data?.zones.map((zone) => ({ value: zone.code, label: `${zone.label} · ${zone.code}` })) ?? []),
  ]

  async function submit() {
    if (submissionPending.current) return
    const next: FieldErrors = {}
    if (!zones.length) next.zone = 'Sélectionnez une zone.'
    if (!sector) next.sector = 'Sélectionnez un secteur.'
    if (!offers.length) next.offers = 'Sélectionnez au moins un type d’offre.'
    if (needsTradeRepair && !buyerTrades.length) next.trades = 'Sélectionnez au moins un corps de métier principal.'
    if (!offer.trim()) next.offer = 'Décrivez ce que vous vendez.'
    if (Object.keys(next).length) {
      setErrors(next)
      return
    }
    submissionPending.current = true
    setSubmitting(true)
    setErrors({})
    try {
      const customerInput = toPayload(zones, sector, offer, offers, buyerTrades, profile?.customer_input)
      const targetId = savedProfileId.current ?? profile?.target_icp_id
      const saved = targetId
        ? await icps.update(targetId, { label: sectorLabel, customer_input: customerInput })
        : await icps.create({ label: sectorLabel, customer_input: customerInput })
      savedProfileId.current = saved.target_icp_id
      if (saved.status !== 'active') {
        setErrors({ general: 'Votre profil est enregistré, mais il reste incomplet. Vérifiez votre zone et votre type d’offre pour continuer.' })
        return
      }
      const me = await refresh()
      if (!me) return // Session expired or changed while the save was running.
      if (me.onboarding_status !== 'ready_for_signals') {
        setErrors({ general: 'Votre profil est enregistré. Son activation n’a pas abouti ; réessayez pour continuer.' })
        return
      }
      navigate(destination, { replace: true, state: { firstSignals: true } })
    } catch (error) {
      setErrors({ general: error instanceof ApiError && error.code === 'territory_limit_exceeded'
        ? 'Votre offre ne permet pas de couvrir ces pays ensemble. Sélectionnez des zones dans un seul pays pour continuer.'
        : savedProfileId.current
          ? 'Votre profil est enregistré, mais la suite n’a pas pu être chargée. Réessayez pour continuer.'
          : 'Impossible d’enregistrer votre profil pour le moment. Vos réponses sont conservées ; réessayez.' })
    } finally {
      submissionPending.current = false
      setSubmitting(false)
    }
  }

  if (session.status === 'authenticated' && session.me.onboarding_status === 'ready_for_signals') {
    return <Navigate to={destination} replace />
  }

  return (
    <AuthShell className="profile-confirmation" eyebrow="Votre veille, à votre mesure" title="Quels marchés vous intéressent ?" description="Précisez votre cible pour retrouver les signaux utiles à votre prospection." wide navigationDisabled={submitting}>
      {profiles.loading || options.loading ? <p role="status" className="auth-state-copy">Chargement de votre profil…</p>
        : profiles.error || options.error ? <div className="profile-load-error" role="alert"><p>Votre profil n’a pas pu être chargé.</p><Button onClick={() => { void profiles.retry(); void options.retry() }}>Réessayer</Button></div>
          : <form onSubmit={(event) => { event.preventDefault(); void submit() }} noValidate aria-busy={submitting}>
            <fieldset disabled={submitting} className="profile-fields">
              <section className="profile-step" aria-labelledby="profile-zone-title">
                <h2 id="profile-zone-title"><span>1</span> Votre zone de prospection</h2>
                <ChoiceList id="confirm-profile-zone" label="Zone" placeholder="Ajouter un département ou un canton" values={zones} choices={zoneChoices} onChange={(values) => {
                  const added = values.find((value) => !zones.includes(value))
                  setZones(!added ? values : values.filter((value) => value === added || (added.includes('-') ? value !== added.split('-')[0] : !value.startsWith(`${added}-`))))
                }} error={errors.zone} />
              </section>
              <section className="profile-step" aria-labelledby="profile-sector-title">
                <h2 id="profile-sector-title"><span>2</span> Les marchés que vous ciblez</h2>
                <div className="form-field">
                  <label htmlFor="confirm-profile-sector">Secteur</label>
                  <select id="confirm-profile-sector" value={sector} onChange={(event) => setSector(event.target.value)} aria-invalid={Boolean(errors.sector)} aria-describedby={errors.sector ? 'sector-error' : undefined}>
                    <option value="">Sélectionner un secteur</option>
                    {customSector ? <option value={sector}>{sectorLabel}</option> : null}
                    {options.data?.sectors.map((item) => <option key={item.prefix} value={item.prefix}>{item.label}</option>)}
                  </select>
                  {errors.sector ? <p id="sector-error" className="form-error" role="alert">{errors.sector}</p> : null}
                </div>
              </section>
              <section className="profile-step" aria-labelledby="profile-offer-title">
                <h2 id="profile-offer-title"><span>3</span> Votre offre commerciale</h2>
                <ChoiceList id="confirm-profile-offers" label="Type d’offre" placeholder="Ajouter un type d’offre" values={offers} choices={OFFER_KINDS.map((value) => ({ value, label: t.offers[value] }))} onChange={(values) => setOffers(values as OfferKind[])} error={errors.offers} />
                <div className="form-field">
                  <label htmlFor="confirm-profile-offer">Ce que vous vendez</label>
                  <Textarea id="confirm-profile-offer" value={offer} onChange={(event) => setOffer(event.target.value)} placeholder="Ex. : charpentes et composants bois pour les entreprises de construction." aria-invalid={Boolean(errors.offer)} aria-describedby={errors.offer ? 'offer-error' : undefined} />
                  {errors.offer ? <p id="offer-error" className="form-error" role="alert">{errors.offer}</p> : null}
                </div>
                {needsTradeRepair && <ChoiceList id="confirm-profile-trades" label="Corps de métier principaux" placeholder="Ajouter un corps de métier" values={buyerTrades} choices={BUYER_TRADES.map((value) => ({ value, label: t.trades[value] }))} onChange={(values) => setBuyerTrades(values as BuyerTrade[])} error={errors.trades} />}
              </section>
            </fieldset>
            <p className="profile-help">{profile?.customer_input.minimum_contract_value?.minimum_amount
              ? 'Votre montant minimum de marché est conservé. Vous pourrez affiner vos critères dans votre profil cible.'
              : 'Tous les montants de marché, sans minimum. Vous pourrez affiner vos critères dans votre profil cible.'}</p>
            {errors.general ? <p className="form-error profile-submit-error" role="alert">{errors.general}</p> : null}
            <Button type="submit" className="profile-submit" disabled={submitting}>{submitting ? 'Enregistrement de votre profil…' : 'Recevoir mes signaux'}{!submitting && <ArrowRight aria-hidden="true" />}</Button>
            <p className="profile-reassurance"><Check aria-hidden="true" /> Votre ciblage reste modifiable à tout moment.</p>
          </form>}
    </AuthShell>
  )
}

function ChoiceList({ id, label, placeholder, values, choices, onChange, error }: {
  id: string; label: string; placeholder: string; values: string[];
  choices: { value: string; label: string }[]; onChange: (values: string[]) => void; error?: string
}) {
  return <div className="form-field">
    <label htmlFor={id}>{label}</label>
    <select id={id} value="" onChange={(event) => {
      if (event.target.value) onChange([...values, event.target.value])
    }} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined}>
      <option value="">{placeholder}</option>
      {choices.filter((item) => !values.includes(item.value)).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
    </select>
    {values.length > 0 && <ul className="profile-choices" aria-label={`${label} : sélection`}>
      {values.map((value) => {
        const text = choices.find((item) => item.value === value)?.label ?? value
        return <li key={value}><span>{text}</span><button type="button" aria-label={`Retirer ${text}`} onClick={() => onChange(values.filter((item) => item !== value))}><X aria-hidden="true" /></button></li>
      })}
    </ul>}
    {error ? <p id={`${id}-error`} className="form-error" role="alert">{error}</p> : null}
  </div>
}
