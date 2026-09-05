import {
  ArrowUpRight,
  CircleUserRound,
  Clock3,
  CreditCard,
  Headphones,
  Languages,
  UserRound,
} from 'lucide-react'
import { useCallback, useState } from 'react'
import { accountData, billing } from '../api/endpoints'
import { useI18n } from '../i18n'
import { SettingsNav } from '../presentation/dashboard/SettingsNav'
import { useResource } from '../presentation/dashboard/resources'
import { Button } from '../presentation/dashboard/ui/button'
import { ReferenceLink } from '../presentation/router/ReferenceLink'

export function Settings() {
  const { locale, t } = useI18n()
  const copy = t.reference.accountSettings
  const loadBilling = useCallback(() => billing.status(), [])
  const access = useResource(loadBilling)
  const [deletionConfirmation, setDeletionConfirmation] = useState('')
  const [dataMessage, setDataMessage] = useState('')

  const downloadExport = async () => {
    const payload = await accountData.export()
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'kivou-account-export.json'
    anchor.click()
    URL.revokeObjectURL(url)
    setDataMessage('Export téléchargé')
  }

  const requestDeletion = async () => {
    if (deletionConfirmation !== 'SUPPRIMER') return
    const result = await accountData.requestDeletion()
    setDataMessage(`Suppression programmée avant le ${new Date(result.scheduled_for).toLocaleString(locale)}`)
  }
  const plan = access.data ? t.reference.plans[access.data.plan_code] : t.reference.missingValue
  const subscriptionStatus = access.data?.subscription_status
  const status = subscriptionStatus && subscriptionStatus in t.billing.status
    ? t.billing.status[subscriptionStatus as keyof typeof t.billing.status]
    : access.data
      ? subscriptionStatus === null
        ? t.billing.status.none
        : t.billing.status.unknown
      : t.reference.missingValue

  const accountSettings = [
    { icon: UserRound, label: copy.users, value: t.reference.missingValue },
    { icon: Languages, label: copy.language, value: locale === 'fr' ? 'Français' : 'English' },
    { icon: Clock3, label: copy.timezone, value: t.reference.missingValue },
  ] as const

  return (
    <div className="settings-main">
      <section className="settings-intro" aria-labelledby="settings-title">
        <p className="section-label">{copy.overviewLabel}</p>
        <h2 id="settings-title">{copy.overviewTitle}</h2>
        <p>{copy.overviewBody}</p>
      </section>

      <SettingsNav active="overview" />

      <div className="settings-layout">
        <section className="settings-account-card" aria-labelledby="account-settings-title">
          <div className="settings-card-heading">
            <div>
              <p className="card-kicker">{copy.preferences}</p>
              <h3 id="account-settings-title">{copy.displayAccess}</h3>
            </div>
            <CircleUserRound aria-hidden="true" />
          </div>

          <dl className="settings-list">
            {accountSettings.map(({ icon: Icon, label, value }) => (
              <div key={label}>
                <span aria-hidden="true"><Icon /></span>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <div className="settings-card-actions">
            <ReferenceLink dashboard className="text-link" href="/settings/profile">
              {copy.editAccount} <ArrowUpRight aria-hidden="true" />
            </ReferenceLink>
            <ReferenceLink dashboard className="text-link" href="/settings/security">
              {copy.securityTitle} <ArrowUpRight aria-hidden="true" />
            </ReferenceLink>
          </div>
        </section>

        <aside className="settings-side">
          <section className="settings-plan-card" aria-labelledby="settings-plan-title">
            <div className="settings-card-heading">
              <div>
                <p className="card-kicker">{copy.subscription}</p>
                <h3 id="settings-plan-title">
                  {access.loading
                    ? t.reference.loading
                    : access.error
                      ? t.reference.missingValue
                      : plan}
                </h3>
                {!access.loading && !access.error ? (
                  <p className="settings-price">
                    <strong>{t.reference.missingValue}</strong>
                    <span>{copy.currentPriceUnavailable}</span>
                  </p>
                ) : null}
              </div>
              <CreditCard aria-hidden="true" />
            </div>

            {access.error ? (
              <div role="alert">
                <p>{t.reference.messages.billingLoadError}</p>
                <button type="button" className="text-link" onClick={() => void access.retry()}>
                  {t.reference.retry}
                </button>
              </div>
            ) : (
              <dl className="settings-plan-facts">
                <div><dt>{copy.users}</dt><dd>{t.reference.missingValue}</dd></div>
                <div><dt>{copy.state}</dt><dd>{access.loading ? t.reference.loading : status}</dd></div>
              </dl>
            )}
            <ReferenceLink dashboard className="text-link" href="/settings/billing">
              {copy.manageSubscription} <ArrowUpRight aria-hidden="true" />
            </ReferenceLink>
          </section>

          <section className="settings-help-card" aria-labelledby="settings-help-title">
            <Headphones aria-hidden="true" />
            <div>
              <p className="card-kicker">{copy.supportKicker}</p>
              <h3 id="settings-help-title">{copy.supportTitle}</h3>
              <p>{copy.supportBody}</p>
              <Button asChild className="primary-action settings-help-action">
                <a href="mailto:contact@kivou.eu">
                  {copy.contact} <ArrowUpRight aria-hidden="true" />
                </a>
              </Button>
            </div>
          </section>
        </aside>
      </div>

      <section className="settings-account-card" aria-labelledby="account-data-title">
        <h3 id="account-data-title">Vos données</h3>
        <p>Téléchargez toutes les données de votre compte au format JSON.</p>
        <Button type="button" onClick={() => void downloadExport()}>Télécharger mes données</Button>
        <h3>Supprimer le compte</h3>
        <p>La suppression sera effective sous 24 heures.</p>
        <label htmlFor="delete-confirmation">Saisissez SUPPRIMER pour confirmer</label>
        <input id="delete-confirmation" value={deletionConfirmation} onChange={(event) => setDeletionConfirmation(event.target.value)} />
        <Button type="button" disabled={deletionConfirmation !== 'SUPPRIMER'} onClick={() => void requestDeletion()}>Supprimer mon compte</Button>
        <p aria-live="polite">{dataMessage}</p>
      </section>
    </div>
  )
}
