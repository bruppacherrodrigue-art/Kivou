import { useRef, useState } from 'react'
import { auth } from '../api/endpoints'
import { emailRequestError, validEmail } from '../api/email'
import type { EmailIdentity } from '../api/types'
import { useResource } from '../presentation/dashboard/resources'
import { Button } from '../presentation/dashboard/ui/button'
import { Input } from '../presentation/dashboard/ui/input'

export function EmailIdentityForm({ onContinue }: { onContinue?: (pendingEmail: string | null) => Promise<void> }) {
  const identity = useResource(auth.email)
  if (identity.error) return <div role="alert">
    <p>Impossible de charger votre adresse email.</p>
    <Button onClick={() => void identity.retry()}>Réessayer</Button>
  </div>
  if (!identity.data) return <p role="status">Chargement de votre adresse email…</p>
  return <LoadedEmailIdentity initial={identity.data} onContinue={onContinue} />
}

function LoadedEmailIdentity({ initial, onContinue }: { initial: EmailIdentity; onContinue?: (pendingEmail: string | null) => Promise<void> }) {
  const [identity, setIdentity] = useState(initial)
  const [email, setEmail] = useState(initial.pending_email ?? initial.email)
  const [sentEmail, setSentEmail] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [continueError, setContinueError] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const busy = useRef(false)
  const address = email.trim()
  const sent = sentEmail === address
  const currentVerified = identity.verified && identity.email === address && !identity.pending_email

  async function send() {
    if (busy.current) return
    setError(null)
    if (!validEmail(address)) { setError('Indiquez une adresse email valide.'); return }
    busy.current = true
    setSubmitting(true)
    setSentEmail(null)
    try {
      await auth.requestEmail(address)
      setIdentity((current) => ({ ...current, pending_email: address }))
      setSentEmail(address)
    } catch (caught) {
      setError(emailRequestError(caught))
    } finally {
      busy.current = false
      setSubmitting(false)
    }
  }

  async function proceed() {
    if (!onContinue || busy.current || !(sent || currentVerified)) return
    busy.current = true
    setSubmitting(true)
    setContinueError(false)
    try { await onContinue(sent ? sentEmail : null) } catch { setContinueError(true) } finally {
      busy.current = false
      setSubmitting(false)
    }
  }

  return <form className="settings-form-card" aria-label="Vérification de l’adresse email" noValidate onSubmit={(event) => { event.preventDefault(); void send() }}>
    <div className="settings-form-heading"><h3>Votre adresse email</h3></div>
    <p>{identity.verified ? 'Adresse vérifiée :' : 'Adresse non vérifiée :'} {identity.email}</p>
    {identity.pending_email ? <p>En attente de vérification : {identity.pending_email}</p> : null}
    <div className="form-field">
      <label htmlFor="identity-email">Adresse professionnelle</label>
      <Input id="identity-email" type="email" autoComplete="email" value={email} disabled={submitting}
        aria-invalid={Boolean(error)} aria-describedby={error ? 'identity-email-help identity-email-error' : 'identity-email-help'}
        onChange={(event) => { setEmail(event.target.value); setError(null); setSentEmail(null) }} />
      <p id="identity-email-help">Validez le lien reçu à cette adresse. Aucune alerte ne sera envoyée à une adresse en attente de vérification.</p>
      {error ? <p className="form-error" role="alert" id="identity-email-error">{error}</p> : null}
    </div>
    {sent ? <p role="status">Lien de vérification envoyé à {sentEmail}. Consultez votre messagerie.</p> : null}
    {continueError ? <p className="form-error" role="alert">Impossible de recharger votre session. Réessayez.</p> : null}
    <div className="settings-form-actions">
      <Button type="submit" disabled={submitting || currentVerified}>
        {submitting ? 'Chargement…' : identity.pending_email === address ? 'Renvoyer le lien de vérification' : 'Envoyer le lien de vérification'}
      </Button>
      {onContinue && (sent || currentVerified) ? <Button type="button" disabled={submitting} onClick={() => void proceed()}>Voir mes signaux</Button> : null}
    </div>
  </form>
}
