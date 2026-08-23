import { useEffect, useState } from 'react'
import { cockpit } from '../api/endpoints'
import type { CockpitMoneyTotal, WeeklyCommercialCockpit } from '../api/types'
import { useCurrentUser } from '../auth/SessionProvider'
import { useI18n, interpolate } from '../i18n'
import styles from './CommercialCockpit.module.css'

const WEEK_OFFSETS = Array.from({ length: 52 }, (_, index) => index)

export function CommercialCockpit() {
  const me = useCurrentUser()
  const { t, money, date, number } = useI18n()
  const [weekOffset, setWeekOffset] = useState(0)
  const [report, setReport] = useState<WeeklyCommercialCockpit | null>(null)
  const [error, setError] = useState(false)

  const allowed = me.capabilities.commercial_cockpit
  useEffect(() => {
    if (!allowed) return
    let current = true
    setReport(null)
    setError(false)
    void cockpit
      .weekly(weekOffset)
      .then((value) => {
        if (current) setReport(value)
      })
      .catch(() => {
        if (current) setError(true)
      })
    return () => {
      current = false
    }
  }, [allowed, weekOffset])

  if (!allowed) {
    return (
      <section className={styles.state}>
        <h1>{t.cockpit.internalRequired}</h1>
        <p>{t.cockpit.internalRequiredBody}</p>
      </section>
    )
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>{t.cockpit.title}</h1>
          <p>{t.cockpit.subtitle}</p>
        </div>
        <label className={styles.weekField}>
          <span>{t.cockpit.weekLabel}</span>
          <select value={weekOffset} onChange={(event) => setWeekOffset(Number(event.target.value))}>
            {WEEK_OFFSETS.map((offset) => (
              <option key={offset} value={offset}>
                {interpolate(t.cockpit.weekOption, { offset })}
              </option>
            ))}
          </select>
        </label>
      </header>

      {error ? <p role="alert" className={styles.error}>{t.cockpit.unavailable}</p> : null}
      {!error && report === null ? <p role="status">{t.common.loading}</p> : null}
      {report ? (
        <>
          {isEmpty(report) ? <p className={styles.empty}>{t.cockpit.empty}</p> : null}
          <section aria-labelledby="cockpit-funnel">
            <h2 id="cockpit-funnel">{t.cockpit.funnelTitle}</h2>
            <div className={styles.funnel}>
              <Metric label={t.cockpit.delivered} value={number(report.funnel.delivered_proxy_count)} />
              <Metric label={t.cockpit.positive} value={number(report.funnel.positive_reply_count)} />
              <Metric label={t.cockpit.clicks} value={number(report.funnel.click_count)} />
              <Metric label={t.cockpit.activated} value={number(report.funnel.activated_account_count)} />
              <Metric label={t.cockpit.paid} value={number(report.funnel.paid_account_count)} />
              <Metric
                label={t.cockpit.mrr}
                value={<MoneyList values={report.funnel.mrr_by_currency} unknown={report.data_quality.unknown_mrr_journey_count > 0} />}
              />
              <Metric label={t.cockpit.churn} value={number(report.funnel.churn_count)} />
            </div>
          </section>

          <section aria-labelledby="cockpit-m2">
            <h2 id="cockpit-m2">{t.cockpit.m2Title}</h2>
            <div className={styles.m2Grid}>
              {report.wedge_m2_efficiency.length === 0 ? <p>—</p> : null}
              {report.wedge_m2_efficiency.map((row) => (
                <article className={styles.m2Card} key={`${row.wedge}:${row.currency ?? 'unknown'}`}>
                  <strong>{row.wedge}</strong>
                  <span>
                    {row.data_status === 'READY' && row.currency && row.retained_m2_mrr_per_1000_delivered
                      ? money(Math.round(Number(row.retained_m2_mrr_per_1000_delivered)), row.currency)
                      : t.cockpit.m2Insufficient}
                  </span>
                  <small>{number(row.retained_m2_accounts)} comptes M2 retenus</small>
                </article>
              ))}
            </div>
          </section>

          <section aria-labelledby="cockpit-table">
            <h2 id="cockpit-table">{t.cockpit.analyticalTitle}</h2>
            <div className={styles.tableWrap}>
              <table aria-label={t.cockpit.analyticalTitle}>
                <thead>
                  <tr>
                    <th>{t.cockpit.country}</th>
                    <th>{t.cockpit.sector}</th>
                    <th>{t.cockpit.need}</th>
                    <th>{t.cockpit.campaign}</th>
                    <th>{t.cockpit.delivered}</th>
                    <th>{t.cockpit.positive}</th>
                    <th>{t.cockpit.clicks}</th>
                    <th>{t.cockpit.activated}</th>
                    <th>{t.cockpit.paid}</th>
                    <th>{t.cockpit.mrr}</th>
                    <th>{t.cockpit.churn}</th>
                  </tr>
                </thead>
                <tbody>
                  {report.analytical_rows.map((row) => (
                    <tr key={`${row.country}:${row.sector_ref}:${row.need_ref}:${row.campaign_ref}`}>
                      <td>{row.country}</td>
                      <td>{row.sector_ref}</td>
                      <td>{row.need_ref}</td>
                      <td><code>{row.campaign_ref}</code></td>
                      <td>{number(row.delivered_proxy_count)}</td>
                      <td>{number(row.positive_reply_count)}</td>
                      <td>{number(row.click_count)}</td>
                      <td>{number(row.activated_account_count)}</td>
                      <td>{number(row.paid_account_count)}</td>
                      <td><MoneyList values={row.mrr_by_currency} unknown={false} /></td>
                      <td>{number(row.churn_count)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <footer className={styles.notes}>
            <p>{t.cockpit.proxyNote}</p>
            <p>{interpolate(t.cockpit.captured, { date: date(report.captured_at) ?? '—' })}</p>
          </footer>
        </>
      ) : null}
    </div>
  )

  function MoneyList({ values, unknown }: { values: CockpitMoneyTotal[]; unknown: boolean }) {
    return (
      <span className={styles.moneyList}>
        {values.length === 0 && !unknown ? '—' : null}
        {values.map((value) => <span key={value.currency}>{money(value.minor_units, value.currency)}</span>)}
        {unknown ? <span>{t.cockpit.incomplete}</span> : null}
      </span>
    )
  }
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <article className={styles.metric}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  )
}

function isEmpty(report: WeeklyCommercialCockpit): boolean {
  const funnel = report.funnel
  return (
    funnel.delivered_proxy_count === 0 &&
    funnel.positive_reply_count === 0 &&
    funnel.click_count === 0 &&
    funnel.activated_account_count === 0 &&
    funnel.paid_account_count === 0 &&
    funnel.mrr_by_currency.length === 0 &&
    funnel.churn_count === 0
  )
}
