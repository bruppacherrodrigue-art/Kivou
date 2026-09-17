import { ArrowRight, CalendarClock, MessageSquare, Sparkles } from 'lucide-react'
import { Link, Navigate, useLocation, useNavigate, useOutletContext } from 'react-router-dom'
import { companies } from '../api/endpoints'
import { useCurrentUser } from '../auth/SessionProvider'
import { useI18n } from '../i18n'
import type { DashboardOutletContext } from '../layouts/AppShell'
import { useProspecting, useProspectingResource } from '../prospecting/ProspectingProvider'
import { SignalListRow } from '../prospecting/components/SignalListRow'
import { SignalDetail } from '../prospecting/components/SignalDetail'
import { TargetBar } from '../prospecting/components/TargetBar'
import { initials } from '../prospecting/adapters'
import styles from '../prospecting/Prospecting.module.css'

export function Dashboard() {
  const me = useCurrentUser()
  if (me.onboarding_status !== 'ready_for_signals' && !me.provisional_profile) return <Navigate to="/app/confirm-profile" replace />
  return <TodayDashboard />
}

function TodayDashboard() {
  const p = useProspecting()
  const { locale, number, date } = useI18n()
  const fr = locale === 'fr'
  const resource = useOutletContext<DashboardOutletContext>()
  const location = useLocation()
  const navigate = useNavigate()
  const selected = new URLSearchParams(location.search).get('signal')
  const replies = useProspectingResource('today-replies', (signal) => companies.list({ ...p.query, contact_status: ['replied'], sort: 'recent', limit: 3 }, { signal }))
  const data = resource.data
  const discoveryPending = Boolean(data?.plan.code === 'discovery' && data.plan.quota != null && data.plan.assigned != null && data.plan.assigned < data.plan.quota)
  const discoveryProgress = data?.plan.code === 'discovery' && data.plan.quota != null && data.plan.assigned != null
    ? data.plan.assigned === 0
      ? (fr ? `Vos ${number(data.plan.quota)} signaux sont en préparation. Kivou sélectionne les meilleures opportunités disponibles.` : `Your ${number(data.plan.quota)} signals are being prepared. Kivou is selecting the best available opportunities.`)
      : (fr ? `${number(data.plan.assigned)} de vos ${number(data.plan.quota)} signaux ${data.plan.assigned === 1 ? 'est disponible' : 'sont disponibles'}. Kivou prépare ${data.plan.remaining === 1 ? 'le suivant' : 'les suivants'}.` : `${number(data.plan.assigned)} of your ${number(data.plan.quota)} signals ${data.plan.assigned === 1 ? 'is' : 'are'} available. Kivou is preparing ${data.plan.remaining === 1 ? 'the next one' : 'the remaining signals'}.`)
    : null
  const link = (path: string, additions: Record<string, string> = {}) => {
    const params = new URLSearchParams(location.search)
    params.delete('signal'); params.delete('presentation_artifact_id'); params.delete('cursor')
    if (path.startsWith('/app/companies')) {
      for (const key of ['view', 'department', 'family', 'q', 'sort', 'contact_status', 'status']) params.delete(key)
    }
    for (const [key, value] of Object.entries(additions)) params.set(key, value)
    return `${path}${params.size ? `?${params}` : ''}`
  }
  const openSignal = (key: string, artifact?: string) => navigate(link(location.pathname, { signal: key, ...(artifact ? { presentation_artifact_id: artifact } : {}) }))
  return <main className={styles.workspace} data-page="today">
    <header className={styles.heading}><div><p className={styles.eyebrow}>{data ? date(data.as_of) : (fr ? 'Votre journée commerciale' : 'Your sales day')}</p><h1>{fr ? 'Aujourd’hui' : 'Today'}</h1><p>{data?.new_since_last_visit ? `${number(data.new_since_last_visit)} ${fr ? 'nouveaux marchés depuis votre dernière visite.' : 'new contracts since your last visit.'}` : (fr ? 'Vos meilleures opportunités et les échanges à poursuivre.' : 'Your best opportunities and the conversations to continue.')}</p></div></header>
    <TargetBar />
    {resource.loading && <section className={styles.panel}><div className={styles.loading} role="status">{fr ? 'Préparation de votre journée…' : 'Preparing your day…'}<div className={styles.skeleton} /><div className={styles.skeleton} /></div></section>}
    {resource.error != null && <section className={styles.error} role="alert"><h2>{fr ? 'Votre journée n’a pas pu être chargée' : 'Your day could not load'}</h2><button className={styles.button} onClick={() => void resource.retry()}>{fr ? 'Réessayer' : 'Retry'}</button></section>}
    {data && <>
      <div className={styles.sectionHeading}><h2>{fr ? 'Vos priorités commerciales' : 'Your sales priorities'}</h2><Link className={styles.textButton} to={link('/app/signals')}>{fr ? 'Tous les signaux' : 'All signals'} <ArrowRight aria-hidden="true" /></Link></div>
      <section className={styles.panel} aria-label={fr ? 'Signaux prioritaires' : 'Priority signals'}>
        {data.top3.length > 0 ? data.top3.map((item) => <SignalListRow key={item.signal_id} item={item} onOpen={() => openSignal(item.signal_id, item.presentation?.artifact_id)} />)
          : !discoveryPending && <div className={styles.empty}><Sparkles aria-hidden="true" /><h3>{fr ? 'Vous êtes à jour' : 'You’re up to date'}</h3><p>{fr ? 'C’est le moment de reprendre vos échanges ou d’explorer de nouvelles entreprises.' : 'Now is a good time to follow up or explore new companies.'}</p><Link className={styles.soft} to={link('/app/signals', { status: 'saved' })}>{fr ? 'Reprendre mes signaux sauvegardés' : 'Return to saved signals'}</Link></div>}
        {discoveryPending && discoveryProgress && <div className={styles.waitingRow} role="status"><span className={styles.waitingDot} aria-hidden="true" /><span>{discoveryProgress}</span></div>}
      </section>
      <div className={styles.sectionHeading} style={{ marginTop: 32 }}><h2>{fr ? 'Faites avancer vos échanges' : 'Move your conversations forward'}</h2><Link className={styles.textButton} to={link('/app/companies')}>{fr ? 'Ma prospection' : 'My prospects'} <ArrowRight aria-hidden="true" /></Link></div>
      <div className={styles.followupGrid}>
        <section className={styles.followup} aria-label={fr ? 'Entreprises à relancer' : 'Companies to follow up'}><CalendarClock aria-hidden="true" /><div>
          <span className={styles.kicker}>{fr ? 'À relancer' : 'Follow up'}</span>
          {data.to_follow_up.length > 0 ? <><h3>{fr ? 'Gardez le lien avec vos prospects' : 'Stay in touch with your prospects'}</h3>{data.to_follow_up.slice(0, 3).map((company) => <div className={styles.reply} key={company.company_key}><div><Link className={styles.companyName} to={link(`/app/companies/${encodeURIComponent(company.company_key)}`)}>{company.name} <ArrowRight aria-hidden="true" /></Link><span className={styles.caption}>{fr ? 'Dernier contact il y a' : 'Last contacted'} {number(company.days_since_contact)} {fr ? 'jours' : 'days ago'}</span></div></div>)}</>
            : <><h3>{fr ? 'Vos prochaines relances se préparent ici' : 'Your next follow-ups start here'}</h3><p>{fr ? 'Marquez une entreprise comme contactée pour la retrouver au bon moment.' : 'Mark a company as contacted to find it here at the right time.'}</p><Link className={styles.textButton} to={link('/app/companies', { contact_status: 'to_contact' })}>{fr ? 'Voir les entreprises à contacter' : 'View companies to contact'} <ArrowRight aria-hidden="true" /></Link></>}
          {data.to_follow_up_truncated && <Link className={styles.textButton} to={link('/app/companies', { contact_status: 'contacted' })}>{fr ? 'Voir toutes mes relances' : 'View all follow-ups'}</Link>}
        </div></section>
        <section className={`${styles.panel} ${styles.replies}`} aria-label={fr ? 'Réponses reçues' : 'Replies received'}><h3><MessageSquare aria-hidden="true" /> {fr ? 'Ils vous ont répondu' : 'They replied'}</h3>
          {replies.loading && <p className={styles.muted} role="status">{fr ? 'Chargement…' : 'Loading…'}</p>}
          {replies.error != null && <p className={styles.error} role="alert">{fr ? 'Les réponses ne sont pas chargées.' : 'Replies could not load.'}<button className={styles.textButton} onClick={replies.reload}>{fr ? 'Réessayer' : 'Retry'}</button></p>}
          {replies.data?.items.map((company) => <div className={styles.reply} key={company.company_key}><span className={styles.avatar} aria-hidden="true">{initials(company.name)}</span><div><Link className={styles.companyName} to={link(`/app/companies/${encodeURIComponent(company.company_key)}`)}>{company.name}</Link><span className={styles.caption}>{company.city}</span></div><ArrowRight aria-hidden="true" /></div>)}
          {replies.data?.items.length === 0 && <p className={styles.muted}>{fr ? 'Les entreprises marquées « A répondu » apparaîtront ici pour poursuivre la conversation.' : 'Companies marked “Replied” will appear here so you can continue the conversation.'}</p>}
        </section>
      </div>
      <section className={styles.week} aria-label={fr ? 'Bilan de la semaine' : 'This week’s summary'}><strong>{fr ? 'Cette semaine' : 'This week'}</strong><span>{number(data.week.new)} {fr ? 'nouveaux signaux' : 'new signals'}</span><span>{number(data.week.saved)} {fr ? 'sauvegardés' : 'saved'}</span><span>{number(data.week.contacted)} {fr ? 'contactés' : 'contacted'}</span><span>{number(data.week.replied)} {fr ? 'réponses' : 'replies'}</span></section>
      {data.scan_truncated && <p className={styles.caption}>{fr ? 'Les résultats présentés couvrent une partie des marchés disponibles. Affinez votre consultation pour aller plus loin.' : 'These results cover part of the available contracts. Refine your view to explore further.'}</p>}
    </>}
    {selected && <SignalDetail key={selected} signalKey={selected} onClose={() => navigate(link(location.pathname), { replace: true })} />}
  </main>
}
