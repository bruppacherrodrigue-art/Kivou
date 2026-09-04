import { Check } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { describeError } from '../api/errorCopy'
import { useCurrentUser, useSession } from '../auth/SessionProvider'
import { useI18n, type Locale } from '../i18n'
import { PrototypeNotice } from '../presentation/dashboard/PrototypeNotice'
import { SettingsNav } from '../presentation/dashboard/SettingsNav'
import { Button } from '../presentation/dashboard/ui/button'
import { Input } from '../presentation/dashboard/ui/input'

const PREFERENCES_RECEIPT = 'accountPreferencesSaved'

function hasSavedReceipt(state: unknown): boolean {
  return Boolean(
    state && typeof state === 'object' && (state as Record<string, unknown>)[PREFERENCES_RECEIPT],
  )
}

function withoutSavedReceipt(state: unknown): Record<string, unknown> | null {
  if (!state || typeof state !== 'object') return null
  const next = { ...(state as Record<string, unknown>) }
  delete next[PREFERENCES_RECEIPT]
  return Object.keys(next).length > 0 ? next : null
}

export function ProfileSettings() {
  const me = useCurrentUser()
  const { updateLocale } = useSession()
  const { t } = useI18n()
  const location = useLocation()
  const navigate = useNavigate()
  const receipt = hasSavedReceipt(location.state)
  const [language, setLanguage] = useState<Locale>(me.locale === 'en' ? 'en' : 'fr')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(receipt)
  const [error, setError] = useState<unknown>(null)
  const mounted = useRef(true)
  const pending = useRef(false)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  useEffect(() => {
    if (!receipt) return
    // Le reçu peut arriver sur l'instance déjà montée avant que la frontière
    // de locale ne la recrée. Il faut donc le refléter dans l'état, pas
    // seulement l'utiliser comme initialiseur de `useState`.
    setSaved(true)
    navigate(location.pathname, {
      replace: true,
      state: withoutSavedReceipt(location.state),
    })
  }, [location.pathname, location.state, navigate, receipt])

  async function savePreferences(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending.current) return
    pending.current = true
    setSaving(true)
    setSaved(false)
    setError(null)

    try {
      await updateLocale(language, () => {
        navigate(location.pathname, {
          replace: true,
          state: {
            ...(location.state && typeof location.state === 'object'
              ? location.state as Record<string, unknown>
              : {}),
            [PREFERENCES_RECEIPT]: true,
          },
        })
      })
      if (mounted.current) setSaved(true)
    } catch (caught) {
      if (mounted.current) setError(caught)
    } finally {
      pending.current = false
      if (mounted.current) setSaving(false)
    }
  }

  const errorCopy = error ? describeError(error, t) : null
  const copy = t.reference.accountSettings

  return (
    <div className="settings-main">
      <section className="settings-intro">
        <p className="section-label">{copy.profileLabel}</p>
        <h2>{copy.profileTitle}</h2>
        <p>{copy.profileBody}</p>
      </section>
      <SettingsNav active="profile" />
      <form
        className="settings-form-card"
        aria-labelledby="account-main-information"
        onSubmit={(event) => void savePreferences(event)}
      >
        <div className="settings-form-heading">
          <div>
            <p className="card-kicker">{copy.identityKicker}</p>
            <h3 id="account-main-information">{copy.mainInformation}</h3>
          </div>
          {saved ? (
            <span className="settings-saved" role="status">
              <Check aria-hidden="true" /> {copy.saved}
            </span>
          ) : null}
        </div>
        <PrototypeNotice>{copy.profileNotice}</PrototypeNotice>
        {errorCopy ? (
          <div className="prototype-notice" role="alert">
            <div>
              <strong>{errorCopy.title}</strong>
              {errorCopy.body ? <p>{errorCopy.body}</p> : null}
            </div>
          </div>
        ) : null}
        <div className="settings-form-grid">
          <div className="form-field">
            <label htmlFor="account-company">{copy.company}</label>
            <Input
              id="account-company"
              autoComplete="organization"
              value={me.account_display_name}
              readOnly
            />
          </div>
          <div className="form-field">
            <label htmlFor="account-email">{copy.professionalEmail}</label>
            <Input id="account-email" type="email" autoComplete="email" value={me.email} readOnly />
          </div>
          <div className="form-field">
            <label htmlFor="account-language">{copy.language}</label>
            <select
              id="account-language"
              className="lifecycle-select"
              value={language}
              disabled={saving}
              onChange={(event) => {
                setLanguage(event.target.value as Locale)
                setSaved(false)
                setError(null)
              }}
            >
              <option value="fr">Français</option>
              <option value="en">English</option>
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="account-timezone">{copy.timezone}</label>
            <select
              id="account-timezone"
              className="lifecycle-select"
              value={t.reference.missingValue}
              disabled
            >
              <option value={t.reference.missingValue}>{t.reference.missingValue}</option>
            </select>
          </div>
        </div>
        <div className="settings-form-actions">
          <Button type="submit" className="primary-action" disabled={saving || language === me.locale}>
            {saving ? copy.saving : copy.savePreferences}
          </Button>
        </div>
      </form>
    </div>
  )
}
