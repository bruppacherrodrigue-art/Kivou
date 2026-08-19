import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useI18n, interpolate } from '../i18n'
import { AuthLayout } from '../layouts/AuthLayout'
import { TextField } from '../components/FormField'
import { Button } from '../components/Button'
import { Callout } from '../components/Surfaces'
import { auth } from '../api/endpoints'
import { describeError } from '../api/errorCopy'
import { MINIMUM_PASSWORD_LENGTH } from '../api/types'
import styles from './AuthPages.module.css'

/** La demande de réinitialisation.
 *
 *  La confirmation est TOUJOURS la même, que le compte existe ou non — le
 *  backend répond d'ailleurs 202 dans les deux cas. Un message qui varierait
 *  transformerait ce formulaire en oracle d'existence de comptes. */
export function ForgotPassword() {
  const { t } = useI18n()
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await auth.requestPasswordReset(email)
      setSent(true)
    } catch (caught) {
      setError(caught)
    } finally {
      setSubmitting(false)
    }
  }

  const errorCopy = error ? describeError(error, t) : null

  return (
    <AuthLayout
      title={t.auth.forgotTitle}
      lead={t.auth.forgotLead}
      footer={
        <Link to="/login" className={styles.footerLink}>
          {t.auth.backToLogin}
        </Link>
      }
    >
      {sent ? (
        <Callout tone="success" title={t.auth.forgotConfirmation} live />
      ) : (
        <form className={styles.form} onSubmit={submit} noValidate>
          {errorCopy ? (
            <Callout tone="danger" title={errorCopy.title} live>
              {errorCopy.body}
            </Callout>
          ) : null}

          <TextField
            label={t.auth.email}
            type="email"
            name="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />

          <Button type="submit" fullWidth size="lg" loading={submitting}>
            {t.auth.forgotSubmit}
          </Button>
        </form>
      )}
    </AuthLayout>
  )
}

/** La confirmation.
 *
 *  Le jeton arrive par l'URL du lien reçu. Il est lu une fois et porté par
 *  l'état du formulaire ; il n'est ni journalisé, ni stocké, ni réaffiché dans
 *  un champ lisible. Le champ de saisie manuelle n'apparaît que si l'URL n'en
 *  contient pas, pour qu'un lien tronqué par un client mail reste rattrapable. */
export function ResetPassword() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const tokenFromUrl = params.get('token') ?? ''

  const [token, setToken] = useState(tokenFromUrl)
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [done, setDone] = useState(false)
  const [touched, setTouched] = useState(false)

  const tooShort = touched && password.length > 0 && password.length < MINIMUM_PASSWORD_LENGTH

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setTouched(true)
    setError(null)
    if (password.length < MINIMUM_PASSWORD_LENGTH) return

    setSubmitting(true)
    try {
      await auth.confirmPasswordReset({ reset_token: token, new_password: password })
      setDone(true)
      // Toutes les sessions ont été révoquées côté serveur : la seule suite
      // possible est une nouvelle connexion.
      setTimeout(() => navigate('/login', { replace: true }), 1200)
    } catch (caught) {
      setError(caught)
    } finally {
      setSubmitting(false)
    }
  }

  const errorCopy = error ? describeError(error, t) : null
  const passwordHelp = interpolate(t.auth.passwordHelp, { min: MINIMUM_PASSWORD_LENGTH })

  return (
    <AuthLayout
      title={t.auth.resetTitle}
      lead={t.auth.resetLead}
      footer={
        <Link to="/login" className={styles.footerLink}>
          {t.auth.backToLogin}
        </Link>
      }
    >
      {done ? (
        <Callout tone="success" title={t.auth.resetDone} live />
      ) : (
        <form className={styles.form} onSubmit={submit} noValidate>
          {errorCopy ? (
            <Callout tone="danger" title={errorCopy.title} live>
              {errorCopy.body}
            </Callout>
          ) : null}

          {tokenFromUrl ? null : (
            <TextField
              label={t.auth.resetTokenLabel}
              name="reset_token"
              required
              value={token}
              onChange={(event) => setToken(event.target.value)}
              help={t.auth.resetTokenHelp}
            />
          )}

          <TextField
            label={t.auth.newPassword}
            type="password"
            name="new_password"
            autoComplete="new-password"
            required
            minLength={MINIMUM_PASSWORD_LENGTH}
            value={password}
            onBlur={() => setTouched(true)}
            onChange={(event) => setPassword(event.target.value)}
            help={passwordHelp}
            error={tooShort ? passwordHelp : null}
          />

          <Button type="submit" fullWidth size="lg" loading={submitting} disabled={!token}>
            {t.auth.resetSubmit}
          </Button>
        </form>
      )}
    </AuthLayout>
  )
}
