import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { icps } from '../api/endpoints'
import type { TargetIcp, TargetIcpInput } from '../api/types'
import { useSession } from '../auth/SessionProvider'
import { AuthShell } from '../presentation/dashboard/AuthShell'
import { Button } from '../presentation/dashboard/ui/button'
import { Textarea } from '../presentation/dashboard/ui/textarea'
import { useResource } from '../presentation/dashboard/resources'

type FieldErrors = Partial<Record<'zone' | 'sector' | 'offer' | 'general', string>>

function initialValue(profile: TargetIcp | undefined, field: 'zones' | 'sector' | 'offer') {
  if (!profile) return field === 'zones' ? [] : ''
  if (field === 'zones') {
    return profile.customer_input.territory_subdivisions?.length
      ? profile.customer_input.territory_subdivisions
      : profile.customer_input.territories
  }
  if (field === 'sector') return profile.customer_input.sector_cpv_prefixes?.[0] ?? ''
  return profile.customer_input.offer_summary
}

function toPayload(zones: string[], sector: string, offer: string): TargetIcpInput {
  return {
    offer_summary: offer.trim(),
    offers: [],
    secondary_offers: [],
    buyer_trades: [],
    secondary_buyer_trades: [],
    territories: [...new Set(zones.map((zone) => zone.split('-', 1)[0]))],
    territory_subdivisions: zones.filter((zone) => zone.includes('-')),
    sector_cpv_prefixes: [sector],
    minimum_contract_value: null,
  }
}

export function ConfirmProfile() {
  const { state: session, refresh } = useSession()
  const navigate = useNavigate()
  const profiles = useResource(useCallback(() => icps.list(), []))
  const options = useResource(useCallback(() => icps.options(), []))
  const provisional = session.status === 'authenticated'
    ? profiles.data?.find((profile) => profile.provisional)
    : undefined
  const [zones, setZones] = useState<string[]>([])
  const [sector, setSector] = useState('')
  const [offer, setOffer] = useState('')
  const [hydratedProfile, setHydratedProfile] = useState<string | null>(null)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!provisional || hydratedProfile === provisional.target_icp_id) return
    setZones(initialValue(provisional, 'zones') as string[])
    setSector(initialValue(provisional, 'sector') as string)
    setOffer(initialValue(provisional, 'offer') as string)
    setHydratedProfile(provisional.target_icp_id)
  }, [hydratedProfile, provisional])

  const sectorLabel = useMemo(
    () => options.data?.sectors.find((item) => item.prefix === sector)?.label
      ?? (provisional?.customer_input.sector_cpv_prefixes?.[0] === sector
        ? provisional.label
        : 'Profil provisoire'),
    [options.data, provisional, sector],
  )
  const provisionalSectorOption = provisional
    && sector
    && !options.data?.sectors.some((item) => item.prefix === sector)
    ? { prefix: sector, label: provisional.label }
    : null

  async function submit() {
    const next: FieldErrors = {}
    if (!zones.length) next.zone = 'Sélectionnez une zone.'
    if (!sector) next.sector = 'Sélectionnez un secteur.'
    if (!offer.trim()) next.offer = 'Décrivez ce que vous vendez.'
    if (Object.keys(next).length) {
      setErrors(next)
      return
    }
    setSubmitting(true)
    setErrors({})
    try {
      const customerInput = toPayload(zones, sector, offer)
      if (provisional) {
        await icps.update(provisional.target_icp_id, { label: sectorLabel, customer_input: customerInput })
      } else {
        await icps.create({ label: sectorLabel, customer_input: customerInput })
      }
      await refresh()
      navigate('/app', { replace: true, state: { firstSignals: true } })
    } catch {
      setErrors({ general: 'Impossible d’enregistrer le profil. Vérifiez les champs puis réessayez.' })
    } finally {
      setSubmitting(false)
    }
  }

  if (profiles.loading || options.loading) {
    return <AuthShell eyebrow="Profil cible" title="Confirmez votre profil cible" description="Chargement…" showBrand={false}><p role="status">Chargement…</p></AuthShell>
  }

  return (
    <AuthShell eyebrow="Profil provisoire" title="Confirmez votre profil cible" description="Trois réponses suffisent pour recevoir vos signaux." wide showBrand={false} navigationDisabled={submitting}>
      <form className="onboarding-step" onSubmit={(event) => { event.preventDefault(); void submit() }} noValidate>
        <div className="onboarding-form-grid">
          <div className="form-field form-field-wide">
            <label htmlFor="confirm-profile-zone">Zone</label>
            <select id="confirm-profile-zone" multiple value={zones} onChange={(event) => setZones(Array.from(event.currentTarget.selectedOptions, (option) => option.value))} aria-invalid={Boolean(errors.zone)}>
              {options.data?.zones.map((zone) => <option key={zone.code} value={zone.code}>{zone.label}</option>)}
            </select>
            {errors.zone ? <p className="form-error" role="alert">{errors.zone}</p> : null}
          </div>
          <div className="form-field form-field-wide">
            <label htmlFor="confirm-profile-sector">Secteur</label>
            <select id="confirm-profile-sector" value={sector} onChange={(event) => setSector(event.target.value)} aria-invalid={Boolean(errors.sector)}>
              <option value="">Sélectionner un secteur</option>
              {provisionalSectorOption ? (
                <option value={provisionalSectorOption.prefix}>{provisionalSectorOption.label}</option>
              ) : null}
              {options.data?.sectors.map((item) => <option key={item.prefix} value={item.prefix}>{item.label}</option>)}
            </select>
            {errors.sector ? <p className="form-error" role="alert">{errors.sector}</p> : null}
          </div>
          <div className="form-field form-field-wide">
            <label htmlFor="confirm-profile-offer">Ce que vous vendez</label>
            <Textarea id="confirm-profile-offer" value={offer} onChange={(event) => setOffer(event.target.value)} aria-invalid={Boolean(errors.offer)} />
            {errors.offer ? <p className="form-error" role="alert">{errors.offer}</p> : null}
          </div>
        </div>
        {errors.general ? <p className="form-error" role="alert">{errors.general}</p> : null}
        <div className="onboarding-actions"><span /><Button type="submit" className="primary-action" disabled={submitting}>Recevoir mes signaux</Button></div>
      </form>
    </AuthShell>
  )
}
