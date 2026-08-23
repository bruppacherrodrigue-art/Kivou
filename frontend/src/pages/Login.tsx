import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useI18n } from '../i18n'
import { AuthLayout } from '../layouts/AuthLayout'
import { TextField } from '../components/FormField'
import { Button } from '../components/Button'
import { Callout } from '../components/Surfaces'
import { useSession } from '../auth/SessionProvider'
import { homeFor } from '../auth/RequireAuth'
import { auth } from '../api/endpoints'
import { describeError } from '../api/errorCopy'
import styles from './AuthPages.module.css'

interface LocationState {
  from?: string
  expired?: boolean
}

export function Login() {
  const { t } = useI18n()
  const { adopt } = useSession()
  const navigate = useNavigate()
  const location = useLocation()
  const state = (location.state ?? {}) as LocationState

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const me = await auth.login({ email, password })
      adopt(me)
      // La règle vit dans `homeFor` : un compte sans profil exploitable va à
      // l'onboarding, et la destination demandée ne s'applique qu'à un compte
      // prêt. La dupliquer ici la ferait diverger de `RedirectIfAuthenticated`.
      const home = homeFor(me)
      const destination =
        me.onboarding_status === 'ready_for_signals' ? (state.from ?? home) : home
      navigate(destination, { replace: true })
    } catch (caught) {
      setError(caught)
    } finally {
      setSubmitting(false)
    }
  }

  const errorCopy = error ? describeError(error, t) : null

  return (
    <AuthLayout
      title={t.auth.loginTitle}
      lead={t.auth.loginLead}
      footer={
        <>
          <span>{t.auth.noAccount}</span>
          <Link to="/signup" className={styles.footerLink}>
            {t.nav.signup}
          </Link>
        </>
      }
    >
      {state.expired ? <Callout tone="warning">{t.auth.sessionExpired}</Callout> : null}

      <form className={styles.form} onSubmit={submit} noValidate>
        {/* Le message est générique : il ne dit jamais si l'adresse existe.
            Le backend applique la même règle, avec un unique code
            `invalid_credentials`. */}
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

        <TextField
          label={t.auth.password}
          type="password"
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        <Button type="submit" fullWidth size="lg" loading={submitting}>
          {t.auth.submitLogin}
        </Button>

        <Link to="/forgot-password" className={styles.inlineLink}>
          {t.auth.forgotLink}
        </Link>
      </form>
    </AuthLayout>
  )
}
