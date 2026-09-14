import type { ReactNode } from 'react'
import { ExternalLink } from 'lucide-react'
import { useI18n } from '../../i18n'
import { durationLabel, formatAmount, safeExternal, signalPlace, signalTitle } from '../adapters'
import type { NoticeDuration, ProspectingSignal } from '../models'
import styles from '../Prospecting.module.css'

export function SignalContent({ item, holder, notes }: { item: ProspectingSignal; holder: ReactNode; notes: ReactNode }) {
  const { locale, date } = useI18n()
  const fr = locale === 'fr'
  const facts = item.notice_facts
  const calendar = facts?.calendar
  const buyerNames = [...new Set(facts?.buyers.length ? facts.buyers.map((buyer) => buyer.name) : [item.contract.buyer?.name].filter((value): value is string => !!value))]
  const source = safeExternal(facts?.source_url) || safeExternal(item.source.url)
  const sourceIdentity = [facts?.source_system || item.source.system, facts?.source_notice_id || item.source.notice_id].filter(Boolean).join(' ')
  const durationTitle = (duration: NoticeDuration) => {
    const noun = duration.scope === 'works' ? (fr ? 'des travaux' : 'of works') : duration.scope === 'purchase_order' ? (fr ? 'd’un bon de commande' : 'of a purchase order') : (fr ? 'du marché' : 'of the contract')
    return `${fr ? 'Durée' : 'Duration'} ${duration.period_kind === 'initial' ? (fr ? 'initiale ' : 'initial ') : duration.period_kind === 'maximum' ? (fr ? 'maximale ' : 'maximum ') : ''}${noun}`
  }
  const durations = calendar ? [calendar.initial_duration, calendar.maximum_duration, calendar.duration].filter((value): value is NoticeDuration => !!value)
    .filter((duration, index, all) => all.findIndex((other) => other.value === duration.value && other.unit === duration.unit && other.scope === duration.scope && other.period_kind === duration.period_kind) === index) : []
  const why = item.commercial_context?.reason
  return <>
    <h2 className={styles.detailTitle}>{signalTitle(item)}</h2>
    <p className={styles.detailMeta}>{[formatAmount(facts?.awarded_amount ?? item.contract.amount, locale), signalPlace(item)].filter(Boolean).join(' · ')}</p>
    {holder}
    {why && <section className={styles.detailSection}><h3>{fr ? 'Pourquoi ça vous concerne' : 'Why this matters to you'}</h3><p>{why}</p></section>}
    {(facts?.publication_date || durations.length > 0 || calendar?.renewals != null) && <section className={styles.detailSection}>
      <h3>{fr ? 'Calendrier' : 'Timeline'}</h3>
      {facts?.publication_date && <p className={styles.muted}>{fr ? 'Avis publié le' : 'Notice published on'} {date(facts.publication_date)}</p>}
      {durations.length > 0 && <dl className={styles.facts}>{durations.map((duration, index) => <div key={`${duration.scope}-${duration.period_kind}-${index}`}><dt>{durationTitle(duration)}</dt><dd>{durationLabel(duration, locale)}</dd>
        {duration.notice_kind === 'contract_notice' && <dd className={styles.muted}>{fr ? 'Selon l’avis de consultation' : 'According to the contract notice'} {safeExternal(duration.source_url) ? <a className={styles.textButton} href={safeExternal(duration.source_url)!} target="_blank" rel="noopener noreferrer">{duration.source_notice_id ?? (fr ? 'Consulter l’avis' : 'Read the notice')} <ExternalLink aria-hidden="true" /></a> : duration.source_notice_id}</dd>}</div>)}</dl>}
      {calendar?.renewals != null && <dl className={styles.facts}><div><dt>{fr ? 'Reconductions possibles' : 'Possible renewals'}</dt><dd>{calendar.renewals}</dd></div></dl>}
    </section>}
    {buyerNames.length > 0 && <section className={styles.detailSection}><h3>{fr ? 'Acheteur' : 'Buyer'}</h3>{buyerNames.map((name) => <p key={name}>{name}</p>)}</section>}
    {(facts?.minimum_amount || facts?.maximum_amount) && <section className={styles.detailSection}><h3>{fr ? 'Cadre du marché' : 'Contract framework'}</h3><dl className={styles.facts}>
      {facts.minimum_amount && <div><dt>{fr ? 'Minimum contractuel' : 'Contract minimum'}</dt><dd>{formatAmount(facts.minimum_amount, locale)}</dd></div>}
      {facts.maximum_amount && <div><dt>{fr ? 'Plafond contractuel' : 'Contract ceiling'}</dt><dd>{formatAmount(facts.maximum_amount, locale)}</dd></div>}
    </dl></section>}
    {facts?.description && <section className={styles.detailSection}><h3>{fr ? 'Détails du marché' : 'Contract details'}</h3><p>{facts.description}</p></section>}
    {facts?.notice_status === 'notice_cancelled' && <p className={styles.error}>{fr ? 'Cet avis a été annulé par la source.' : 'This notice has been cancelled by the source.'}</p>}
    {notes}
    {source ? <a className={styles.textButton} href={source} target="_blank" rel="noopener noreferrer">{fr ? 'Consulter l’avis' : 'Read the notice'} {sourceIdentity} <ExternalLink aria-hidden="true" /></a> : <p className={styles.muted}>{fr ? 'Source :' : 'Source:'} {sourceIdentity}</p>}
  </>
}
