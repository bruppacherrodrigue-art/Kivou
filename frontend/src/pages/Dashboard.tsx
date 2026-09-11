import { useState } from 'react'
import { Link, Navigate, useOutletContext } from 'react-router-dom'
import { feedback, signals as signalApi } from '../api/endpoints'
import type { UnlockedFeedItem } from '../api/types'
import { useCurrentUser } from '../auth/SessionProvider'
import { useI18n } from '../i18n'
import type { DashboardOutletContext } from '../layouts/AppShell'
import { MatchDots } from '../signals/components/MatchDots'
import { SignalDrawer } from '../signals/components/SignalDrawer'
import { MISSING, placeLabel, signalObject } from '../signals/components/SignalRow'
import { monthLabel } from '../signals/valueFormat'
import styles from './Dashboard.module.css'
import { ScreenHeader, SummaryRow } from '../components/ScreenChrome'
import { sharedZoneLabels } from '../presentation/dashboard/zoneLabels'

export function Dashboard() {
  const me = useCurrentUser()
  if (me.onboarding_status !== 'ready_for_signals') return <Navigate to="/app/confirm-profile" replace />
  return <TodayDashboard />
}

function TodayDashboard() {
  const { locale, amount, shortDate } = useI18n()
  const resource = useOutletContext<DashboardOutletContext>()
  const [selected, setSelected] = useState<UnlockedFeedItem | null>(null)
  const [drawerLoading, setDrawerLoading] = useState(false)
  const [drawerError, setDrawerError] = useState<unknown | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [actionError, setActionError] = useState(false)

  const ignore = async (item: UnlockedFeedItem) => {
    setBusy(item.signal_id)
    setActionError(false)
    try {
      await feedback.write(item.signal_id, { relevance: 'not_relevant' })
      setSelected((current) => current?.signal_id === item.signal_id ? null : current)
      await resource.retry()
    } catch {
      setActionError(true)
    } finally {
      setBusy(null)
    }
  }

  const drawerAction = async (status: 'saved' | 'ignored' | 'contacted') => {
    if (!selected) return
    setBusy(selected.signal_id)
    try {
      if (status === 'contacted') await feedback.markContacted(selected.signal_id)
      else await feedback.write(selected.signal_id, {
        relevance: status === 'saved' ? 'relevant' : 'not_relevant',
        ...(status === 'ignored' ? { reason: 'other' as const } : {}),
      })
      setSelected({ ...selected, status })
      await resource.retry()
    } finally {
      setBusy(null)
    }
  }

  const openSignal = async (item: UnlockedFeedItem) => {
    setSelected(item)
    setDrawerLoading(true)
    setDrawerError(null)
    try {
      const detail = await signalApi.detail(item.signal_id)
      if (!detail.locked) setSelected(detail)
    } catch (error) {
      setDrawerError(error)
    } finally {
      setDrawerLoading(false)
    }
  }

  if (resource.loading && !resource.data) return <main className={styles.page}><p role="status">Chargement…</p></main>
  if (resource.error || !resource.data) return <main className={styles.page}><p role="alert">Le résumé n’a pas pu être chargé.</p><button type="button" onClick={() => void resource.retry()}>Réessayer</button></main>

  const data = resource.data
  const title = data.last_seen_at
    ? data.new_since_last_visit === 0
      ? `Rien de nouveau depuis ${weekday(data.last_seen_at, locale)} · ${data.week.new} signaux cette semaine`
      : `${data.new_since_last_visit} nouveaux marchés depuis ${weekday(data.last_seen_at, locale)}`
    : 'Vos premiers signaux'
  const zoneLabels = sharedZoneLabels(data.profile)
  const matchContext = [data.profile?.sector_label, zoneLabels.join(', ')].filter(Boolean).join(' · ')

  return (
    <main className={styles.page} data-page="today">
      <ScreenHeader title={title} description={data.strong_matches > 0
        ? `${data.strong_matches} correspondent fortement à votre profil${matchContext ? ` ${matchContext}` : ''}` : undefined} />

      {actionError ? <p className={styles.error} role="alert">Le signal n’a pas pu être ignoré. Réessayez.</p> : null}
      {data.top3.length ? (
        <section className={styles.cards} aria-label="Signaux prioritaires">
          {data.top3.map((item) => (
            <article className={styles.card} key={item.signal_id}>
              <div className={styles.cardHead}>{item.company.name ? <strong>{item.company.name}</strong> : null}<MatchDots item={item} /></div>
              {signalObject(item) ? <p className={styles.object} title={signalObject(item) ?? undefined}>{signalObject(item)}</p> : null}
              {(() => {
                const money = amount(item.contract.amount?.value, item.contract.amount?.currency)
                const place = placeLabel(item.contract.location, locale)
                const eventDate = shortDate(item.factual_display.date.value)
                const context = [place === MISSING ? null : place, eventDate].filter(Boolean).join(' · ')
                return money || context ? <div className={styles.meta}>{money ? <strong>{money}</strong> : null}{context ? <span>{context}</span> : null}</div> : null
              })()}
              {item.commercial_calendar && monthLabel(item.commercial_calendar.start_month, locale) ? (
                <p className={styles.calendar}>
                  Démarrage probable {monthLabel(item.commercial_calendar.start_month, locale)}
                </p>
              ) : null}
              {item.analysis.fit.for_you_sentence ?? item.analysis.fit.reasons[0] ? <p className={styles.reason}><b>Pour vous :</b> {item.analysis.fit.for_you_sentence ?? item.analysis.fit.reasons[0]}</p> : null}
              <div className={styles.actions}>
                <button type="button" className={styles.primary} onClick={() => void openSignal(item)}>Ouvrir</button>
                <button type="button" disabled={busy === item.signal_id} onClick={() => void ignore(item)}>Ignorer</button>
              </div>
            </article>
          ))}
        </section>
      ) : (
        <section className={styles.empty} aria-label="Signaux prioritaires">
          <p>Aucun nouveau signal prioritaire pour le moment.</p>
          <Link to="/app/signals">Voir tous les signaux</Link>
        </section>
      )}

      <div className={styles.lower}>
        <section className={styles.list} aria-label="À relancer">
          <h2>À relancer</h2>
          {data.to_follow_up.length ? data.to_follow_up.map((item) => (
            <div className={styles.followUp} key={item.company_key}>
              <span><b>{item.name}</b>{signalObject(item.last_signal) ? <small>{signalObject(item.last_signal)}</small> : null}</span>
              <span>contactée il y a {item.days_since_contact} j</span>
              <Link to={`/app/companies/${item.company_key}`}>Ouvrir</Link>
            </div>
          )) : <p className={styles.muted}>Aucune entreprise à relancer.</p>}
        </section>
        <section className={styles.list} aria-label="Cette semaine">
          <h2>Cette semaine</h2>
          <SummaryRow label="Nouveaux marchés" value={data.week.new} />
          <SummaryRow label="Sauvés" value={data.week.saved} />
          <SummaryRow label="Entreprises contactées" value={data.week.contacted} />
          <SummaryRow label="Ont répondu" value={data.week.replied} />
        </section>
      </div>

      {selected ? (
        <div className={styles.drawerLayer}>
          <button className={styles.backdrop} type="button" aria-label="Fermer" onClick={() => setSelected(null)} />
          <SignalDrawer
            item={selected}
            loading={drawerLoading}
            error={drawerError}
            busy={busy === selected.signal_id}
            onClose={() => setSelected(null)}
            onRetry={() => void openSignal(selected)}
            onContacted={() => void drawerAction('contacted')}
            onSave={() => void drawerAction('saved')}
            onIgnore={() => void drawerAction('ignored')}
          />
        </div>
      ) : null}
    </main>
  )
}

function weekday(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale === 'fr' ? 'fr-FR' : 'en-GB', { weekday: 'long', timeZone: 'UTC' })
    .format(new Date(value))
}
