import { useEffect, useState } from 'react'
import { useI18n } from '../i18n'
import { Callout, Card, SectionHeading, Skeleton } from '../components/Surfaces'
import { Button } from '../components/Button'
import { Switch, TextField } from '../components/FormField'
import { billing, notifications } from '../api/endpoints'
import { ApiError } from '../api/client'
import { describeError } from '../api/errorCopy'
import type { AlertCadence, NotificationPreference } from '../api/types'
import styles from './Notifications.module.css'

/* Les préférences de notification.
 *
 * La cadence n'est PAS réglable : elle découle du plan. Elle vient de
 * `billing/status → entitlements.alert_cadence`, en lecture seule, parce que la
 * proposer comme un choix laisserait croire qu'un compte Découverte peut
 * s'abonner à des alertes quotidiennes.
 *
 * Le libellé de Scale est « prioritaire », jamais « temps réel » ni
 * « instantané ». Le backend a renommé cette cadence précisément pour ne pas
 * promettre une latence qu'un traitement planifié ne tient pas.
 *
 * Aucun historique de livraison n'est affiché : la remise SMTP est un point de
 * déploiement, et inventer un journal d'envois serait une donnée fabriquée.
 */
export function Notifications() {
  const { t } = useI18n()
  const [preference, setPreference] = useState<NotificationPreference | null>(null)
  const [cadence, setCadence] = useState<AlertCadence | null>(null)
  const [email, setEmail] = useState('')
  const [enabled, setEnabled] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [saveError, setSaveError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let active = true
    Promise.all([notifications.read(), billing.status().catch(() => null)])
      .then(([pref, status]) => {
        if (!active) return
        setPreference(pref)
        setEnabled(pref.email_enabled)
        setEmail(pref.notification_email ?? '')
        setCadence(status?.entitlements.alert_cadence ?? null)
      })
      .catch((caught) => {
        if (active) setError(caught)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  async function save() {
    setSaveError(null)
    setSaved(false)
    setSaving(true)
    try {
      const next = await notifications.update({
        email_enabled: enabled,
        notification_email: email.trim() === '' ? null : email.trim(),
      })
      setPreference(next)
      setEnabled(next.email_enabled)
      setEmail(next.notification_email ?? '')
      setSaved(true)
    } catch (caught) {
      setSaveError(caught)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className={styles.page}>
        <SectionHeading title={t.notifications.title} lead={t.notifications.lead} level={1} />
        <Card padding="lg">
          <Skeleton width="50%" height="1.5rem" />
        </Card>
      </div>
    )
  }

  if (error || !preference) {
    const copy = describeError(error, t)
    return (
      <div className={styles.page}>
        <SectionHeading title={t.notifications.title} lead={t.notifications.lead} level={1} />
        <Callout tone="danger" title={t.notifications.errorTitle} live>
          {copy.body ?? copy.title}
        </Callout>
      </div>
    )
  }

  // Une adresse refusée appartient au CHAMP, pas à un bandeau général : le
  // message doit se lire à côté de ce qu'il faut corriger.
  const emailFieldError =
    saveError instanceof ApiError && saveError.code === 'invalid_notification_email'
      ? t.notifications.invalidEmail
      : null
  // Le bandeau ne reprend PAS un message déjà porté par un champ : le lire deux
  // fois ne le rend pas plus clair, et un lecteur d'écran l'annoncerait deux fois.
  const saveCopy = saveError && !emailFieldError ? describeError(saveError, t) : null
  const dirty =
    enabled !== preference.email_enabled ||
    email.trim() !== (preference.notification_email ?? '')

  return (
    <div className={styles.page}>
      <SectionHeading title={t.notifications.title} lead={t.notifications.lead} level={1} />

      <Card padding="lg" as="section" className={styles.card}>
        <Switch
          label={t.notifications.enabled}
          help={t.notifications.enabledHelp}
          checked={enabled}
          onChange={(next) => {
            setEnabled(next)
            setSaved(false)
          }}
        />

        <TextField
          label={t.notifications.emailLabel}
          type="email"
          value={email}
          help={t.notifications.emailHelp}
          onChange={(event) => {
            setEmail(event.target.value)
            setSaved(false)
          }}
          error={emailFieldError}
        />

        <div className={styles.cadence}>
          <p className={styles.cadenceLabel}>{t.notifications.cadenceLabel}</p>
          <p className={styles.cadenceValue}>
            {cadence ? t.notifications.cadence[cadence] : t.common.notAvailable}
          </p>
          <p className={styles.cadenceHelp}>
            {cadence === 'none' ? t.notifications.cadenceNoneHelp : t.notifications.cadenceHelp}
          </p>
        </div>

        {saveCopy ? (
          <Callout tone="danger" title={saveCopy.title} live>
            {saveCopy.body}
          </Callout>
        ) : null}

        <div className={styles.actions}>
          <Button loading={saving} disabled={!dirty} onClick={() => void save()}>
            {t.common.save}
          </Button>
          {saved ? (
            <p className={styles.saved} role="status">
              {t.notifications.updated}
            </p>
          ) : null}
        </div>
      </Card>
    </div>
  )
}
