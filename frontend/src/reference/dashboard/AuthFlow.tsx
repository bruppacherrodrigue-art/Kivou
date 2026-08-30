import { useEffect, useRef, useState } from 'react'
import { ArrowRight, CheckCircle2, Info } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { auth } from '../../api/endpoints'
import { describeError } from '../../api/errorCopy'
import { MINIMUM_PASSWORD_LENGTH } from '../../api/types'
import { homeFor } from '../../auth/RequireAuth'
import { useSession } from '../../auth/SessionProvider'
import { planFromSearch, planSearch } from '../../billing/planRoute'
import { useI18n } from '../../i18n'
import { fr } from '../../i18n/fr'
import { AuthShell } from './AuthShell'
import { PasswordField } from './PasswordField'
import { Button } from './ui/button'
import { Checkbox } from './ui/checkbox'
import { Input } from './ui/input'

export type AuthMode = 'login' | 'signup' | 'forgot' | 'reset'

const copy: Record<AuthMode, { eyebrow: string; title: string; description: string }> = {
  login: {
    eyebrow: 'Connexion',
    title: 'Retrouver vos signaux',
    description: 'Accédez à votre ciblage, aux attributions documentées et à vos notes.',
  },
  signup: {
    eyebrow: 'Création du compte',
    title: 'Commencer avec un ciblage clair',
    description: 'Créez votre accès, puis décrivez simplement ce que vous vendez et à qui.',
  },
  forgot: {
    eyebrow: 'Accès au compte',
    title: 'Réinitialiser le mot de passe',
    description: 'Indiquez l’adresse utilisée pour votre compte Kivou.',
  },
  reset: {
    eyebrow: 'Nouveau mot de passe',
    title: 'Choisir un nouvel accès',
    description: 'Utilisez un mot de passe unique d’au moins douze caractères.',
  },
}

const noticeCopy: Record<AuthMode, string> = {
  login: 'La connexion utilise votre compte et votre session Kivou réels.',
  signup: 'Le compte sera créé par Kivou avant la configuration de votre ciblage.',
  forgot: 'Pour protéger les comptes, le même message sera affiché quelle que soit l’adresse.',
  reset: 'Le nouveau mot de passe sera transmis à Kivou et fermera les autres sessions.',
}

const COMPANY_REQUIRED = 'Indiquez le nom de votre entreprise.'
const EMAIL_INVALID = 'Indiquez une adresse e-mail valide.'
const PASSWORD_REQUIRED = 'Indiquez votre mot de passe.'

function resetTokenFromSearch(search: string): string {
  return new URLSearchParams(search).get('token')?.trim() ?? ''
}

interface LocationState {
  from?: string
  expired?: boolean
}

function messageFor(error: unknown): string {
  if (typeof error === 'string') return error
  const copy = describeError(error, fr)
  return `${copy.title} ${copy.body}`.trim()
}

export function AuthFlow({ mode }: { mode: AuthMode }) {
  const { adopt } = useSession()
  const { locale } = useI18n()
  const location = useLocation()
  const navigate = useNavigate()
  const locationState = (location.state ?? {}) as LocationState
  const selectedPlan = planFromSearch(location.search)

  const [email, setEmail] = useState('')
  const [company, setCompany] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const urlResetToken = resetTokenFromSearch(location.search)
  const [resetToken, setResetToken] = useState(() => urlResetToken)
  const [accepted, setAccepted] = useState(false)
  const [complete, setComplete] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const emailRef = useRef<HTMLInputElement>(null)
  const busyRef = useRef(false)
  const mountedRef = useRef(false)
  const generationRef = useRef(0)
  const resetTimerRef = useRef<number | null>(null)
  const pageCopy = copy[mode]

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      generationRef.current += 1
      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current)
        resetTimerRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    generationRef.current += 1
    busyRef.current = false
    setSubmitting(false)
    if (mode === 'reset') setResetToken(urlResetToken)
  }, [mode, location.search, urlResetToken])

  useEffect(() => {
    document.documentElement.lang = 'fr'
    return () => {
      document.documentElement.lang = locale
    }
  }, [locale])

  const requestIsCurrent = (generation: number) =>
    mountedRef.current && generationRef.current === generation

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busyRef.current) return
    setError(null)

    if (mode === 'signup' && !company.trim()) {
      setError(COMPANY_REQUIRED)
      return
    }
    if (mode !== 'reset' && (!email.trim() || emailRef.current?.validity.valid === false)) {
      setError(EMAIL_INVALID)
      return
    }
    if ((mode === 'login' || mode === 'signup') && password.length === 0) {
      setError(PASSWORD_REQUIRED)
      return
    }
    if ((mode === 'signup' || mode === 'reset') && password !== confirmation) {
      setError('Les deux mots de passe ne correspondent pas.')
      return
    }
    if ((mode === 'signup' || mode === 'reset') && password.length < MINIMUM_PASSWORD_LENGTH) {
      setError(`Le mot de passe doit contenir au moins ${MINIMUM_PASSWORD_LENGTH} caractères.`)
      return
    }
    if (mode === 'signup' && !accepted) {
      setError('Veuillez accepter les conditions pour poursuivre.')
      return
    }
    if (mode === 'reset' && !resetToken.trim()) {
      setError('Le jeton de réinitialisation est requis.')
      return
    }

    busyRef.current = true
    const generation = ++generationRef.current
    setSubmitting(true)
    try {
      if (mode === 'login') {
        const me = await auth.login({ email, password })
        if (!requestIsCurrent(generation)) return
        adopt(me)
        const home = homeFor(me)
        const selectedHome = selectedPlan === 'discovery'
          ? home
          : me.onboarding_status === 'ready_for_signals'
            ? `/app/billing${planSearch(selectedPlan)}`
            : `/onboarding${planSearch(selectedPlan)}`
        const destination =
          me.onboarding_status === 'ready_for_signals'
            ? (locationState.from ?? selectedHome)
            : selectedHome
        navigate(destination, { replace: true })
      } else if (mode === 'signup') {
        const me = await auth.signup({
          company_name: company,
          email,
          password,
          locale: 'fr',
        })
        if (!requestIsCurrent(generation)) return
        adopt(me)
        navigate(`/onboarding${planSearch(selectedPlan)}`, { replace: true })
      } else if (mode === 'forgot') {
        await auth.requestPasswordReset(email)
        if (!requestIsCurrent(generation)) return
        setComplete(true)
      } else {
        await auth.confirmPasswordReset({
          reset_token: resetToken,
          new_password: password,
        })
        if (!requestIsCurrent(generation)) return
        setComplete(true)
        resetTimerRef.current = window.setTimeout(() => {
          resetTimerRef.current = null
          if (requestIsCurrent(generation)) navigate('/login', { replace: true })
        }, 1200)
      }
    } catch (caught) {
      if (requestIsCurrent(generation)) setError(caught)
    } finally {
      if (requestIsCurrent(generation)) {
        busyRef.current = false
        setSubmitting(false)
      }
    }
  }

  if (complete) {
    const resetComplete = mode === 'reset'
    return (
      <AuthShell {...pageCopy}>
        <div className="auth-success" role="status">
          <CheckCircle2 aria-hidden="true" />
          <div>
            <strong>{resetComplete ? 'Mot de passe remplacé' : 'Demande prise en compte'}</strong>
            <p>
              {resetComplete
                ? 'Le changement est enregistré. Vous allez revenir à la connexion.'
                : 'Si un compte correspond à cette adresse, Kivou enverra un lien de réinitialisation.'}
            </p>
          </div>
        </div>
        <Button asChild className="primary-action auth-submit">
          <Link to="/login">Revenir à la connexion</Link>
        </Button>
      </AuthShell>
    )
  }

  const errorMessage = error ? messageFor(error) : null
  const invalidPassword =
    errorMessage !== null &&
    (mode === 'signup' || mode === 'reset') &&
    password.length < MINIMUM_PASSWORD_LENGTH

  function reportNativeError(event: React.InvalidEvent<HTMLFormElement>) {
    event.preventDefault()
    const field = event.target as HTMLInputElement
    if (field.id === 'signup-company') setError(COMPANY_REQUIRED)
    else if (field.type === 'email') setError(EMAIL_INVALID)
    else if (field.type === 'password') {
      setError(
        field.validity.tooShort
          ? `Le mot de passe doit contenir au moins ${MINIMUM_PASSWORD_LENGTH} caractères.`
          : PASSWORD_REQUIRED,
      )
    }
  }

  function blockNavigation(event: React.MouseEvent<HTMLAnchorElement>) {
    if (busyRef.current) event.preventDefault()
  }

  return (
    <AuthShell {...pageCopy} navigationDisabled={submitting}>
      {locationState.expired ? (
        <p className="form-error" role="alert">Votre session a expiré. Reconnectez-vous.</p>
      ) : null}

      <div className="prototype-notice" role="note">
        <Info aria-hidden="true" />
        <p>{noticeCopy[mode]}</p>
      </div>

      <form className="auth-form" onSubmit={submit} onInvalid={reportNativeError}>
        {mode === 'signup' ? (
          <div className="form-field">
            <label htmlFor="signup-company">Entreprise</label>
            <Input
              id="signup-company"
              autoComplete="organization"
              placeholder="Votre entreprise"
              value={company}
              required
              aria-invalid={errorMessage === COMPANY_REQUIRED || undefined}
              onChange={(event) => setCompany(event.target.value)}
            />
          </div>
        ) : null}

        {mode !== 'reset' ? (
          <div className="form-field">
            <label htmlFor={`${mode}-email`}>Adresse e-mail professionnelle</label>
            <Input
              id={`${mode}-email`}
              ref={emailRef}
              type="email"
              autoComplete="email"
              placeholder="vous@entreprise.ch"
              value={email}
              required
              aria-invalid={errorMessage === EMAIL_INVALID || undefined}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
        ) : null}

        {mode === 'login' || mode === 'signup' ? (
          <PasswordField
            id={`${mode}-password`}
            label="Mot de passe"
            value={password}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            hint={mode === 'signup' ? '12 caractères minimum.' : undefined}
            minLength={mode === 'login' ? 1 : MINIMUM_PASSWORD_LENGTH}
            invalid={invalidPassword}
            onChange={setPassword}
          />
        ) : null}

        {mode === 'reset' ? (
          <>
            {urlResetToken ? null : (
              <div className="form-field">
                <label htmlFor="reset-token">Jeton de réinitialisation</label>
                <Input
                  id="reset-token"
                  autoComplete="off"
                  value={resetToken}
                  required
                  onChange={(event) => setResetToken(event.target.value)}
                />
              </div>
            )}
            <PasswordField
              id="reset-password"
              label="Nouveau mot de passe"
              value={password}
              autoComplete="new-password"
              hint="12 caractères minimum. Le changement fermera les autres sessions."
              invalid={invalidPassword}
              onChange={setPassword}
            />
          </>
        ) : null}

        {mode === 'signup' || mode === 'reset' ? (
          <PasswordField
            id={`${mode}-confirmation`}
            label={mode === 'reset' ? 'Confirmer le nouveau mot de passe' : 'Confirmer le mot de passe'}
            value={confirmation}
            autoComplete="new-password"
            invalid={errorMessage === 'Les deux mots de passe ne correspondent pas.'}
            onChange={setConfirmation}
          />
        ) : null}

        {mode === 'signup' ? (
          <div className="form-field">
            <span className="auth-readonly-label">Langue</span>
            <output className="lifecycle-select auth-readonly-locale">Français</output>
          </div>
        ) : null}

        {mode === 'login' ? (
          <div className="auth-inline-row">
            <span />
            <Link className="text-link" to="/forgot-password" aria-disabled={submitting || undefined} onClick={blockNavigation}>Mot de passe oublié ?</Link>
          </div>
        ) : null}

        {mode === 'signup' ? (
          <label className="auth-consent">
            <Checkbox
              checked={accepted}
              onCheckedChange={(value) => setAccepted(value === true)}
            />
            <span>
              J’accepte les <Link to="/informations-legales#cgu" target="_blank" rel="noreferrer">conditions d’utilisation</Link>.
            </span>
          </label>
        ) : null}

        {errorMessage ? <p className="form-error" role="alert">{errorMessage}</p> : null}

        <Button type="submit" className="primary-action auth-submit" disabled={submitting}>
          {mode === 'login'
            ? 'Se connecter'
            : mode === 'signup'
              ? 'Continuer vers le ciblage'
              : mode === 'forgot'
                ? 'Demander un lien'
                : 'Valider le nouveau mot de passe'}
          <ArrowRight aria-hidden="true" />
        </Button>
      </form>

      <p className="auth-footer-copy">
        {mode === 'login' ? (
          <>Pas encore de compte ? <Link to={`/signup${planSearch(selectedPlan)}`} aria-disabled={submitting || undefined} onClick={blockNavigation}>Créer un compte</Link></>
        ) : mode === 'signup' ? (
          <>Déjà un compte ? <Link to={`/login${planSearch(selectedPlan)}`} aria-disabled={submitting || undefined} onClick={blockNavigation}>Se connecter</Link></>
        ) : (
          <>Vous avez retrouvé votre accès ? <Link to="/login" aria-disabled={submitting || undefined} onClick={blockNavigation}>Se connecter</Link></>
        )}
      </p>
    </AuthShell>
  )
}
