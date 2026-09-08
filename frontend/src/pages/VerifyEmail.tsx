import { useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { auth } from '../api/endpoints'
import { homeFor } from '../auth/RequireAuth'
import { useSession } from '../auth/SessionProvider'
import { AuthShell } from '../presentation/dashboard/AuthShell'
import { Button } from '../presentation/dashboard/ui/button'

export function VerifyEmail() {
  const location = useLocation()
  const navigate = useNavigate()
  const { adopt } = useSession()
  const [token] = useState(() => location.hash.slice(1))
  const [verified, setVerified] = useState(false)
  const [destination, setDestination] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(token ? null : 'Ce lien est invalide ou expiré.')
  const [submitting, setSubmitting] = useState(false)
  const busy = useRef(false)

  async function verify() {
    if (busy.current || !token || destination) return
    busy.current = true
    setSubmitting(true)
    setError(null)
    let accepted = verified
    try {
      if (!accepted) {
        await auth.verifyEmail(token)
        accepted = true
        setVerified(true)
        navigate(location.pathname, { replace: true })
      }
      // The POST rotates the HttpOnly cookie. Read the authoritative session
      // explicitly so a failed read can be retried without reusing the token.
      const me = await auth.me()
      adopt(me)
      setDestination(homeFor(me))
    } catch (caught) {
      setError(accepted ? 'Votre adresse est vérifiée, mais la session n’a pas pu être chargée. Réessayez.'
        : caught instanceof ApiError && caught.status === 400 ? 'Ce lien est invalide ou expiré.'
        : 'La vérification a échoué. Réessayez.')
    } finally {
      busy.current = false
      setSubmitting(false)
    }
  }

  return <AuthShell eyebrow="Votre adresse email" title="Vérifiez votre adresse email" description="Confirmez votre adresse avec le bouton ci-dessous.">
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {verified ? <p role="status">Votre adresse email est vérifiée.</p> : null}
    {destination ? <Link className="primary-action" to={destination}>Voir mes signaux</Link> : token ?
      <Button type="button" disabled={submitting} onClick={() => void verify()}>{submitting ? 'Vérification…' : verified ? 'Réessayer la connexion' : 'Vérifier mon adresse email'}</Button> : null}
    <p><Link to="/app/settings/profile">Demander un nouveau lien</Link></p>
  </AuthShell>
}
