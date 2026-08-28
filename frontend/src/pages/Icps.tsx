import { useEffect, useState } from 'react'
import { useI18n, interpolate } from '../i18n'
import { Badge, Callout, Card, EmptyState, SectionHeading, Skeleton } from '../components/Surfaces'
import { Button } from '../components/Button'
import { NoSignalIllustration } from '../assets/Illustrations'
import { CompletenessNotice, IcpFields, emptyIcpValue, missingFields } from './IcpForm'
import type { IcpFormValue } from './IcpForm'
import { billing, icps as icpsApi } from '../api/endpoints'
import { MVP_TERRITORIES, territoryLabel } from '../api/capabilities'
import { describeError } from '../api/errorCopy'
import type { BillingStatus, TargetIcp } from '../api/types'
import styles from './Icps.module.css'

/* La gestion des profils de ciblage.
 *
 * La suppression n'est PAS implémentée : le backend n'expose aucun `DELETE`
 * sur `/target-icps`. Un bouton qui ne peut aboutir n'a pas sa place, et un
 * profil au-delà de la limite du plan est CONSERVÉ — le client tranche, Kivou
 * ne supprime rien dans son dos.
 */
export function Icps() {
  const { t } = useI18n()
  const [profiles, setProfiles] = useState<TargetIcp[] | null>(null)
  const [status, setStatus] = useState<BillingStatus | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [editing, setEditing] = useState<string | 'new' | null>(null)

  async function reload() {
    try {
      const [list, billingStatus] = await Promise.all([
        icpsApi.list(),
        billing.status().catch(() => null),
      ])
      setProfiles(list)
      setStatus(billingStatus)
      setError(null)
    } catch (caught) {
      setError(caught)
    }
  }

  useEffect(() => {
    void reload()
  }, [])

  const limit = status?.entitlements.max_active_icps
  const overLimit = new Set(status?.target_icps_over_limit ?? [])
  const activeCount = profiles?.filter((profile) => profile.status === 'active').length ?? 0

  if (error && profiles === null) {
    const copy = describeError(error, t)
    return (
      <div className={styles.page}>
        <SectionHeading title={t.icp.title} lead={t.icp.lead} level={1} hideTitle />
        <Callout
          tone="danger"
          title={copy.title}
          live
          action={
            <Button variant="secondary" onClick={() => void reload()}>
              {t.common.retry}
            </Button>
          }
        >
          {copy.body}
        </Callout>
      </div>
    )
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <SectionHeading title={t.icp.title} lead={t.icp.lead} level={1} hideTitle />
        {editing === null ? (
          <Button onClick={() => setEditing('new')}>{t.icp.create}</Button>
        ) : null}
      </header>

      {limit !== undefined ? (
        <p className={styles.limit}>
          {t.icp.limitLabel} : <span className="kivou-tabular">{activeCount}</span> /{' '}
          <span className="kivou-tabular">{limit}</span>
        </p>
      ) : null}

      {/* Un dépassement est MONTRÉ, jamais masqué ni résolu par une
          suppression silencieuse. */}
      {overLimit.size > 0 && status ? (
        <Callout tone="warning" title={t.icp.overLimitBadge}>
          {interpolate(t.icp.limitReached, {
            plan: t.billing.plans[status.plan_code],
            limit: status.entitlements.max_active_icps,
          })}
        </Callout>
      ) : null}

      {editing === 'new' ? (
        <IcpEditor
          initial={emptyIcpValue()}
          onCancel={() => setEditing(null)}
          onSave={async (value) => {
            await icpsApi.create({ label: value.label.trim(), customer_input: value.input })
            await reload()
            setEditing(null)
          }}
        />
      ) : null}

      {profiles === null ? (
        <div className={styles.list}>
          {[0, 1].map((index) => (
            <Card key={index} padding="md">
              <Skeleton width="40%" height="1.25rem" />
            </Card>
          ))}
        </div>
      ) : profiles.length === 0 && editing === null ? (
        <Card padding="none">
          <EmptyState
            illustration={<NoSignalIllustration />}
            title={t.icp.listEmpty}
            body={t.icp.listEmptyBody}
            action={<Button onClick={() => setEditing('new')}>{t.icp.create}</Button>}
          />
        </Card>
      ) : (
        <ul className={styles.list}>
          {profiles.map((profile) =>
            editing === profile.target_icp_id ? (
              <li key={profile.target_icp_id}>
                <IcpEditor
                  initial={{ label: profile.label, input: profile.customer_input }}
                  onCancel={() => setEditing(null)}
                  onSave={async (value) => {
                    await icpsApi.update(profile.target_icp_id, {
                      label: value.label.trim(),
                      customer_input: value.input,
                    })
                    await reload()
                    setEditing(null)
                  }}
                />
              </li>
            ) : (
              <li key={profile.target_icp_id}>
                <IcpSummary
                  profile={profile}
                  overLimit={overLimit.has(profile.target_icp_id)}
                  onEdit={() => setEditing(profile.target_icp_id)}
                />
              </li>
            ),
          )}
        </ul>
      )}
    </div>
  )
}

function IcpSummary({
  profile,
  overLimit,
  onEdit,
}: {
  profile: TargetIcp
  overLimit: boolean
  onEdit: () => void
}) {
  const { t, locale, amount } = useI18n()
  const input = profile.customer_input
  const ready = profile.status === 'active'
  const territories = input.territories.map((code) => {
    const territory = MVP_TERRITORIES.find((candidate) => candidate.code === code)
    return territory ? territoryLabel(territory, locale) : code
  })
  const threshold = input.minimum_contract_value
    ? amount(
        String(input.minimum_contract_value.minimum_amount),
        input.minimum_contract_value.currency,
      )
    : null
  const offerSummary = input.offer_summary.trim()
  const territoryPlanLimit = profile.plan_limit

  return (
    <Card padding="md" as="article" className={styles.card}>
      <div className={styles.cardHead}>
        <h2 className={styles.cardTitle}>{profile.label}</h2>
        <div className={styles.badges}>
          <Badge tone={ready ? 'positive' : 'warm'}>
            {ready ? t.onboarding.statusReady : t.onboarding.statusIncomplete}
          </Badge>
          {overLimit ? <Badge tone="warm">{t.icp.overLimitBadge}</Badge> : null}
          {territoryPlanLimit ? (
            <Badge tone="warm">{t.icp.territoryLimitedBadge}</Badge>
          ) : null}
        </div>
      </div>

      {profile.missing_fields.length > 0 ? (
        <CompletenessNotice missing={profile.missing_fields} />
      ) : null}

      {overLimit ? <p className={styles.overLimitHelp}>{t.icp.overLimitHelp}</p> : null}

      {territoryPlanLimit ? (
        <p className={styles.overLimitHelp}>
          {interpolate(
            territoryPlanLimit.limit === 1
              ? t.icp.territoryLimitedHelpOne
              : t.icp.territoryLimitedHelpOther,
            { limit: territoryPlanLimit.limit },
          )}
        </p>
      ) : null}

      <dl className={styles.summary}>
        <div>
          <dt>{t.icp.offersLabel}</dt>
          <dd>
            {input.offers.length > 0
              ? input.offers.map((offer) => t.offers[offer]).join(', ')
              : t.common.notAvailable}
          </dd>
        </div>
        <div>
          <dt>{t.icp.tradesLabel}</dt>
          <dd>
            {input.buyer_trades.length > 0
              ? input.buyer_trades.map((trade) => t.trades[trade]).join(', ')
              : t.icp.noTrades}
          </dd>
        </div>
        <div>
          <dt>{t.icp.territoriesLabel}</dt>
          <dd>
            {territories.length > 0 ? territories.join(', ') : t.common.notAvailable}
          </dd>
        </div>
        <div>
          <dt>{t.icp.thresholdLabel}</dt>
          <dd className="kivou-tabular">
            {threshold ?? t.common.notAvailable}
          </dd>
        </div>
        {offerSummary ? (
          <div className={styles.summaryDescription}>
            <dt>{t.onboarding.summaryLabel}</dt>
            <dd>{offerSummary}</dd>
          </div>
        ) : null}
      </dl>

      <div className={styles.cardActions}>
        <Button variant="secondary" onClick={onEdit}>
          {t.icp.edit}
        </Button>
      </div>
    </Card>
  )
}

function IcpEditor({
  initial,
  onSave,
  onCancel,
}: {
  initial: IcpFormValue
  onSave: (value: IcpFormValue) => Promise<void>
  onCancel: () => void
}) {
  const { t } = useI18n()
  const [value, setValue] = useState<IcpFormValue>(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const missing = missingFields(value)
  const canSave = value.label.trim().length > 0

  async function save() {
    setError(null)
    setSaving(true)
    try {
      await onSave(value)
    } catch (caught) {
      setError(caught)
    } finally {
      setSaving(false)
    }
  }

  const copy = error ? describeError(error, t) : null

  return (
    <Card padding="lg" as="section" className={styles.editor}>
      <h2 className={styles.cardTitle}>{t.icp.editTitle}</h2>

      {copy ? (
        <Callout tone="danger" title={copy.title} live>
          {copy.body}
        </Callout>
      ) : null}

      <IcpFields value={value} onChange={setValue} error={error} />
      <CompletenessNotice missing={missing} />

      <div className={styles.cardActions}>
        <Button loading={saving} disabled={!canSave} onClick={() => void save()}>
          {t.common.save}
        </Button>
        <Button variant="secondary" onClick={onCancel} disabled={saving}>
          {t.common.cancel}
        </Button>
      </div>
    </Card>
  )
}
