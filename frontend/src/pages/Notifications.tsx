import { Check, Mail } from 'lucide-react'
import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { billing, notifications } from '../api/endpoints'
import { describeError } from '../api/errorCopy'
import type { AlertCadence, NotificationPreference } from '../api/types'
import { useCurrentUser } from '../auth/SessionProvider'
import { useI18n } from '../i18n'
import { PrototypeNotice } from '../reference/dashboard/PrototypeNotice'
import { SettingsNav } from '../reference/dashboard/SettingsNav'
import { useResource } from '../reference/dashboard/resources'
import { Button } from '../reference/dashboard/ui/button'
import { Input } from '../reference/dashboard/ui/input'
import { Switch } from '../reference/dashboard/ui/switch'

interface NotificationDraft {
  enabled: boolean
  email: string
}

const EMPTY_DRAFT: NotificationDraft = { enabled: false, email: '' }

function preferenceDraft(preference: NotificationPreference): NotificationDraft {
  return {
    enabled: preference.email_enabled,
    email: preference.notification_email ?? '',
  }
}

function normaliseDraft(draft: NotificationDraft): NotificationDraft {
  return { enabled: draft.enabled, email: draft.email.trim() }
}

function sameDraft(left: NotificationDraft, right: NotificationDraft): boolean {
  const normalisedLeft = normaliseDraft(left)
  const normalisedRight = normaliseDraft(right)
  return normalisedLeft.enabled === normalisedRight.enabled
    && normalisedLeft.email === normalisedRight.email
}

export function Notifications() {
  const me = useCurrentUser()
  const { t } = useI18n()
  const copy = t.reference.notificationSettings
  const loadPreference = useCallback(() => notifications.read(), [])
  const loadCadence = useCallback(() => billing.status(), [])
  const preferenceResource = useResource(loadPreference)
  const cadenceResource = useResource(loadCadence)
  const [baseline, setBaseline] = useState<NotificationDraft | null>(null)
  const [draft, setDraft] = useState(EMPTY_DRAFT)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<unknown>(null)
  const [emptyEmailError, setEmptyEmailError] = useState(false)
  const loadedPreference = useRef<NotificationPreference | null>(null)
  const draftRef = useRef(draft)
  const mounted = useRef(true)
  const saveGeneration = useRef(0)
  const busyRef = useRef(false)
  const accountId = me.account_id

  useEffect(() => {
    draftRef.current = draft
  }, [draft])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      saveGeneration.current += 1
      busyRef.current = false
    }
  }, [])

  useEffect(() => {
    const preference = preferenceResource.data
    if (!preference || loadedPreference.current === preference) return
    loadedPreference.current = preference
    const next = preferenceDraft(preference)
    draftRef.current = next
    setBaseline(next)
    setDraft(next)
    setSaved(false)
    setSaveError(null)
  }, [preferenceResource.data])

  const dirty = baseline !== null && !sameDraft(draft, baseline)
  const cadence = !cadenceResource.loading && !cadenceResource.error
    ? cadenceResource.data?.entitlements.alert_cadence ?? null
    : null

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busyRef.current || !baseline || !dirty) return

    const snapshot = normaliseDraft(draftRef.current)
    if (snapshot.enabled && snapshot.email === '') {
      setEmptyEmailError(true)
      setSaved(false)
      return
    }
    const generation = ++saveGeneration.current
    const startedForAccount = accountId
    busyRef.current = true
    setSaving(true)
    setSaved(false)
    setSaveError(null)

    try {
      const response = await notifications.update({
        email_enabled: snapshot.enabled,
        notification_email: snapshot.email === '' ? null : snapshot.email,
      })
      if (
        !mounted.current ||
        generation !== saveGeneration.current ||
        startedForAccount !== accountId
      ) return

      const next = preferenceDraft(response)
      setBaseline(next)
      if (sameDraft(snapshot, draftRef.current)) {
        draftRef.current = next
        setDraft(next)
        setSaved(true)
      }
    } catch (caught) {
      if (
        mounted.current &&
        generation === saveGeneration.current &&
        startedForAccount === accountId
      ) {
        setSaveError(caught)
      }
    } finally {
      if (
        mounted.current &&
        generation === saveGeneration.current &&
        startedForAccount === accountId
      ) {
        busyRef.current = false
        setSaving(false)
      }
    }
  }

  const emailFieldError = emptyEmailError
    ? copy.recipientRequired
    : saveError instanceof ApiError && saveError.code === 'invalid_notification_email'
      ? t.notifications.invalidEmail
      : null
  const saveCopy = saveError && !emailFieldError ? describeError(saveError, t) : null

  return (
    <div className="settings-main">
      <section className="settings-intro">
        <p className="section-label">{copy.label}</p>
        <h2>{copy.title}</h2>
        <p>{copy.body}</p>
      </section>
      <SettingsNav active="notifications" />

      {preferenceResource.loading && baseline === null ? (
        <section className="settings-form-card" aria-labelledby="notification-form-title" aria-busy="true">
          <NotificationHeading saved={false} />
          <p role="status">{copy.preferencesLoading}</p>
        </section>
      ) : preferenceResource.error || baseline === null ? (
        <section className="settings-form-card" aria-labelledby="notification-form-title">
          <NotificationHeading saved={false} />
          <PrototypeNotice>{copy.connectedNotice}</PrototypeNotice>
          <div className="prototype-notice" role="alert">
            <div>
              <strong>{copy.preferencesError}</strong>
              <Button type="button" variant="outline" onClick={() => void preferenceResource.retry()}>
                {copy.retryPreferences}
              </Button>
            </div>
          </div>
        </section>
      ) : (
        <form
          className="settings-form-card"
          aria-labelledby="notification-form-title"
          noValidate
          onSubmit={(event) => void save(event)}
        >
          <NotificationHeading saved={saved} />
          <PrototypeNotice>{copy.connectedNotice}</PrototypeNotice>

          <div className="notification-toggle-row">
            <span className="notification-icon"><Mail aria-hidden="true" /></span>
            <div>
              <strong>{copy.receive}</strong>
              <p>{copy.receiveBody}</p>
            </div>
            <Switch
              checked={draft.enabled}
              disabled={saving}
              aria-label={copy.activate}
              onCheckedChange={(enabled) => {
                const next = { ...draftRef.current, enabled }
                draftRef.current = next
                setDraft(next)
                setSaved(false)
                setSaveError(null)
                setEmptyEmailError(false)
              }}
            />
          </div>

          <div className="settings-form-grid">
            <div className="form-field">
              <label htmlFor="notification-recipient">{copy.recipient}</label>
              <Input
                id="notification-recipient"
                type="email"
                value={draft.email}
                disabled={!draft.enabled || saving}
                required={draft.enabled}
                aria-invalid={emailFieldError ? true : undefined}
                aria-describedby={emailFieldError ? 'notification-email-error' : undefined}
                onChange={(event) => {
                  const next = { ...draftRef.current, email: event.target.value }
                  draftRef.current = next
                  setDraft(next)
                  setSaved(false)
                  setSaveError(null)
                  setEmptyEmailError(false)
                }}
              />
              {emailFieldError ? (
                <p id="notification-email-error" className="form-error" role="alert">
                  {emailFieldError}
                </p>
              ) : null}
            </div>

            <div className="form-field">
              <label htmlFor="notification-frequency">{copy.frequency}</label>
              <select
                id="notification-frequency"
                className="lifecycle-select"
                value={cadence ?? ''}
                disabled
                aria-describedby="notification-frequency-hint"
              >
                {cadence === null ? (
                  <option value="">
                    {cadenceResource.loading ? copy.cadenceLoading : t.reference.missingValue}
                  </option>
                ) : null}
                {cadenceOptions(t).map((option) => (
                  <option value={option.value} key={option.value}>{option.label}</option>
                ))}
              </select>
              <p id="notification-frequency-hint" className="field-hint">
                {cadence === 'none' ? t.notifications.cadenceNoneHelp : copy.frequencyHint}
              </p>
              {cadenceResource.error ? (
                <div className="prototype-notice" role="alert">
                  <div>
                    <strong>{copy.cadenceError}</strong>
                    <Button type="button" variant="outline" onClick={() => void cadenceResource.retry()}>
                      {copy.retryCadence}
                    </Button>
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          {saveCopy ? (
            <div className="prototype-notice" role="alert">
              <div>
                <strong>{saveCopy.title}</strong>
                {saveCopy.body ? <p>{saveCopy.body}</p> : null}
              </div>
            </div>
          ) : null}

          <div className="settings-form-actions">
            <Button
              type="submit"
              className="primary-action"
              disabled={saving || !dirty}
            >
              {saving ? t.reference.saving : copy.save}
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}

function NotificationHeading({ saved }: { saved: boolean }) {
  const { t } = useI18n()
  const copy = t.reference.notificationSettings
  return (
    <div className="settings-form-heading">
      <div>
        <p className="card-kicker">{copy.kicker}</p>
        <h3 id="notification-form-title">{copy.delivery}</h3>
      </div>
      {saved ? (
        <span className="settings-saved" role="status">
          <Check aria-hidden="true" /> {t.reference.saved}
        </span>
      ) : null}
    </div>
  )
}

function cadenceOptions(t: ReturnType<typeof useI18n>['t']): {
  value: AlertCadence
  label: string
}[] {
  return (['none', 'weekly', 'daily', 'priority'] as const).map((value) => ({
    value,
    label: t.notifications.cadence[value],
  }))
}
