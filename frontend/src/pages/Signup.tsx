import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { auth } from '../api/endpoints'
import type { DiscoveryPreviewOptions } from '../api/types'
import { useSession } from '../auth/SessionProvider'
import { AuthFlow } from '../presentation/dashboard/AuthFlow'
import { AuthShell } from '../presentation/dashboard/AuthShell'
import { Button } from '../presentation/dashboard/ui/button'

function DiscoverySignup() {
  const navigate = useNavigate()
  const { adopt } = useSession()
  const [options, setOptions] = useState<DiscoveryPreviewOptions | null>(null)
  const [zone, setZone] = useState('')
  const [sector, setSector] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let active = true
    void auth.discoveryPreviewOptions().then(
      (value) => { if (active) setOptions(value) },
      () => { if (active) setError('Les choix ne peuvent pas être chargés. Réessayez.') },
    )
    return () => { active = false }
  }, [])

  async function submit() {
    if (!zone || !sector || submitting) return
    setSubmitting(true)
    setError('')
    try {
      const preview = await auth.createDiscoveryPreview({ zone, sector })
      if (preview.landing_cohort.materialized < 1) throw new Error('empty preview')
      navigate(`/app/signals/${encodeURIComponent(preview.signal_id)}`, { replace: true })
      adopt(preview.me)
    } catch (caught) {
      setError(caught instanceof ApiError && caught.code === 'landing_access_unavailable'
        ? 'Aucun marché récent ne peut être affiché pour ce profil. Essayez un secteur voisin.'
        : 'Vos signaux ne peuvent pas être chargés pour le moment. Réessayez.')
      setSubmitting(false)
    }
  }

  return (
    <AuthShell
      eyebrow="Essai Découverte"
      title="Quels marchés vous intéressent ?"
      description="Choisissez votre zone et votre secteur. Vos trois premiers signaux s’ouvrent immédiatement."
      navigationDisabled={submitting}
    >
      {!options && !error ? <p role="status" className="auth-state-copy">Chargement des secteurs…</p> : null}
      {options ? (
        <form className="auth-form" onSubmit={(event) => { event.preventDefault(); void submit() }}>
          <div className="form-field">
            <label htmlFor="discovery-zone">Zone</label>
            <select id="discovery-zone" className="lifecycle-select" value={zone} onChange={(event) => setZone(event.target.value)} required disabled={submitting}>
              <option value="">Sélectionner un département</option>
              {options.zones.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="discovery-sector">Secteur</label>
            <select id="discovery-sector" className="lifecycle-select" value={sector} onChange={(event) => setSector(event.target.value)} required disabled={submitting}>
              <option value="">Sélectionner un secteur</option>
              {options.sectors.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
            </select>
          </div>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <Button className="auth-submit" type="submit" disabled={!zone || !sector || submitting}>
            {submitting ? 'Préparation de vos signaux…' : 'Recevoir mes signaux'}
          </Button>
        </form>
      ) : error ? <div className="auth-actions"><p className="form-error" role="alert">{error}</p><Button onClick={() => window.location.reload()}>Réessayer</Button></div> : null}
    </AuthShell>
  )
}

export function Signup() {
  const location = useLocation()
  return new URLSearchParams(location.search).get('plan') === 'discovery'
    ? <DiscoverySignup />
    : <AuthFlow mode="signup" />
}
