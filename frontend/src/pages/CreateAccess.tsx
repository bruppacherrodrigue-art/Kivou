import { useRef, useState } from 'react'
import { ArrowRight, CheckCircle2 } from 'lucide-react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { auth } from '../api/endpoints'
import { ApiError } from '../api/client'
import { MINIMUM_PASSWORD_LENGTH } from '../api/types'
import { useCurrentUser, useSession } from '../auth/SessionProvider'
import { AuthShell } from '../presentation/dashboard/AuthShell'
import { PasswordField } from '../presentation/dashboard/PasswordField'
import { Button } from '../presentation/dashboard/ui/button'
import { Input } from '../presentation/dashboard/ui/input'

interface ClaimLocationState { returnTo?: string }

function isDurableEmail(value: string): boolean {
  const normalized = value.trim().toLowerCase()
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalized)
    && !normalized.endsWith('@landing.kivou.invalid')
}

function safeReturnTo(value: string | undefined): string {
  return value?.startsWith('/app/') && value !== '/app/create-access'
    ? value
    : '/app/signals'
}

export function CreateAccess() {
  const me = useCurrentUser()
  const { adopt } = useSession()
  const location = useLocation()
  const navigate = useNavigate()
  const destination = safeReturnTo((location.state as ClaimLocationState | null)?.returnTo)
  const invitationEmail = me.claim_email && isDurableEmail(me.claim_email) ? me.claim_email : null
  const [email, setEmail] = useState(invitationEmail ?? '')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const pending = useRef(false)

  if (!me.temporary_access) return <Navigate to={destination} replace />

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending.current) return
    setError(null)
    if (!isDurableEmail(email)) {
      setError('Saisissez une adresse e-mail professionnelle valide.')
      return
    }
    if (password.length < MINIMUM_PASSWORD_LENGTH) {
      setError(`Le mot de passe doit contenir au moins ${MINIMUM_PASSWORD_LENGTH} caractères.`)
      return
    }
    if (password !== confirmation) {
      setError('Les deux mots de passe ne correspondent pas.')
      return
    }
    pending.current = true
    setSubmitting(true)
    try {
      const claimed = await auth.claimAccess(password, invitationEmail ? undefined : email.trim())
      adopt(claimed)
      navigate(destination, { replace: true })
    } catch (caught) {
      setError(caught instanceof ApiError && caught.code === 'email_already_used'
        ? 'Un accès existe déjà avec cette adresse. Connectez-vous ou utilisez « Mot de passe oublié ».'
        : caught instanceof ApiError && caught.code === 'landing_access_unavailable'
          ? 'Cette adresse ne peut pas être utilisée. Actualisez la page puis réessayez.'
          : caught instanceof ApiError && caught.code === 'invalid_claim_email'
            ? 'Saisissez une adresse e-mail professionnelle durable.'
          : 'Votre accès n’a pas pu être créé. Réessayez dans un instant.')
    } finally {
      pending.current = false
      setSubmitting(false)
    }
  }

  return <AuthShell
    className="claim-access"
    eyebrow="Votre accès Kivou"
    title="Créez votre mot de passe"
    description="Sécurisez votre compte pour retrouver vos signaux à tout moment."
    navigationDisabled={submitting}
  >
    <div className="prototype-notice" role="note">
      <CheckCircle2 aria-hidden="true" />
      <p>Votre signal et votre profil cible sont déjà enregistrés.</p>
    </div>
    <form className="auth-form" onSubmit={submit}>
      <div className="form-field">
        <label htmlFor="claim-email">Adresse e-mail professionnelle</label>
        <Input id="claim-email" type="email" autoComplete="email" value={email} readOnly={Boolean(invitationEmail)} required onChange={(event) => setEmail(event.target.value)} />
      </div>
      <PasswordField id="claim-password" label="Créer mon mot de passe" value={password} autoComplete="new-password" hint="12 caractères minimum." invalid={Boolean(error) && password.length < MINIMUM_PASSWORD_LENGTH} onChange={setPassword} />
      <PasswordField id="claim-confirmation" label="Confirmer le mot de passe" value={confirmation} autoComplete="new-password" invalid={error === 'Les deux mots de passe ne correspondent pas.'} onChange={setConfirmation} />
      {error && <p className="form-error" role="alert">{error}</p>}
      <Button type="submit" className="primary-action auth-submit" disabled={submitting || !isDurableEmail(email) || password.length < MINIMUM_PASSWORD_LENGTH || password !== confirmation}>
        {submitting ? 'Création de votre accès…' : 'Créer mon accès'}
        {!submitting && <ArrowRight aria-hidden="true" />}
      </Button>
    </form>
  </AuthShell>
}
