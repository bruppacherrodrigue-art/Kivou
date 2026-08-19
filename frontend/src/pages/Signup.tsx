import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useI18n, interpolate, LOCALES } from '../i18n'
import type { Locale } from '../i18n'
import { AuthLayout } from '../layouts/AuthLayout'
import { SelectField, TextField } from '../components/FormField'
import { Button } from '../components/Button'
import { Callout } from '../components/Surfaces'
import { useSession } from '../auth/SessionProvider'
import { auth } from '../api/endpoints'
import { describeError, fieldError } from '../api/errorCopy'
import { MINIMUM_PASSWORD_LENGTH } from '../api/types'
import styles from './AuthPages.module.css'

/* L'inscription.
 *
 * Les quatre champs correspondent EXACTEMENT au contrat `SignupRequest` :
 * email, password, company_name, locale. Le schéma pydantic refuse tout champ
 * supplémentaire (`extra="forbid"`), donc en inventer un ferait échouer la
 * requête en 422 — et surtout, en inventer un promettrait au client qu'une
 * information est prise en compte alors qu'elle ne serait jamais lue.
 */
export function Signup() {
  const { t, locale: uiLocale } = useI18n()
  const { adopt } = useSession()
  const navigate = useNavigate()

  const [companyName, setCompanyName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [locale, setLocale] = useState<Locale>(uiLocale)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [touched, setTouched] = useState(false)

  const passwordTooShort = touched && password.length > 0 && password.length < MINIMUM_PASSWORD_LENGTH

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setTouched(true)
    setError(null)

    if (password.length < MINIMUM_PASSWORD_LENGTH) return

    setSubmitting(true)
    try {
      const me = await auth.signup({
        email,
        password,
        company_name: companyName,
        locale,
      })
      adopt(me)
      // Un compte neuf n'a aucun profil : l'onboarding est la seule suite utile.
      navigate('/onboarding', { replace: true })
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
      title={t.auth.signupTitle}
      lead={t.auth.signupLead}
      footer={
        <>
          <span>{t.auth.hasAccount}</span>
          <Link to="/login" className={styles.footerLink}>
            {t.nav.login}
          </Link>
        </>
      }
    >
      <form className={styles.form} onSubmit={submit} noValidate>
        {errorCopy ? (
          <Callout tone="danger" title={errorCopy.title} live>
            {errorCopy.body}
          </Callout>
        ) : null}

        <TextField
          label={t.auth.companyName}
          name="company_name"
          autoComplete="organization"
          required
          value={companyName}
          onChange={(event) => setCompanyName(event.target.value)}
          error={fieldError(error, 'company_name')}
        />

        <TextField
          label={t.auth.email}
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          error={fieldError(error, 'email')}
        />

        <TextField
          label={t.auth.password}
          type="password"
          name="password"
          autoComplete="new-password"
          required
          minLength={MINIMUM_PASSWORD_LENGTH}
          value={password}
          onBlur={() => setTouched(true)}
          onChange={(event) => setPassword(event.target.value)}
          help={passwordHelp}
          error={passwordTooShort ? passwordHelp : fieldError(error, 'password')}
        />

        <SelectField
          label={t.auth.locale}
          name="locale"
          value={locale}
          onChange={(event) => setLocale(event.target.value as Locale)}
        >
          {LOCALES.map((option) => (
            <option key={option} value={option}>
              {option === 'fr' ? t.common.french : t.common.english}
            </option>
          ))}
        </SelectField>

        <Button type="submit" fullWidth size="lg" loading={submitting}>
          {t.auth.submitSignup}
        </Button>
      </form>
    </AuthLayout>
  )
}
