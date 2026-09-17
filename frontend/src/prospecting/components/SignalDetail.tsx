import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Bookmark, Check, RotateCcw } from 'lucide-react'
import { companies, signals } from '../../api/endpoints'
import { useCurrentUser } from '../../auth/SessionProvider'
import { useI18n } from '../../i18n'
import { signalClock } from '../adapters'
import type { ProspectingSignal } from '../models'
import { useProspecting, useProspectingResource } from '../ProspectingProvider'
import { useSignalActions } from '../useSignalActions'
import { useCompanyEnrichment } from '../useCompanyEnrichment'
import { DetailFrame } from './DetailFrame'
import { HolderSummary } from './HolderSummary'
import { CompanyEnrichmentStatus } from './CompanyEnrichmentStatus'
import { SignalContent } from './SignalContent'
import { NotesField } from './NotesField'
import { UpgradeDialog } from './UpgradeDialog'
import { statusLabel } from './SignalListRow'
import styles from '../Prospecting.module.css'

export function SignalDetail({ signalKey, onClose }: { signalKey: string; onClose: () => void }) {
  const me = useCurrentUser()
  const p = useProspecting()
  const { locale, date } = useI18n()
  const fr = locale === 'fr'
  const location = useLocation()
  const navigate = useNavigate()
  const artifact = new URLSearchParams(location.search).get('presentation_artifact_id')
  const resource = useProspectingResource('signal-detail', (signal) => signals.detail(signalKey, { ...p.query, presentation_artifact_id: artifact }, { signal }), { signalKey, artifact }, true, { allowWithoutScope: true })
  const detail = resource.data
  const item: ProspectingSignal | null = detail && !detail.locked ? detail : null
  const holder = useProspectingResource('signal-holder', (signal) => companies.dossier(item!.company_key!, { signal }), { companyKey: item?.company_key ?? null }, !!item?.company_key && !item?.landing_demo, { scopeIndependent: true })
  const actions = useSignalActions(item)
  const enrichment = useCompanyEnrichment(holder.data, { initialLookup: holder.data?.contact_lookup, initialDirectoryEnrichment: holder.data?.directory_enrichment })
  const holderProfile = enrichment.dossier ?? holder.data
  const lookup = enrichment.state === 'idle' ? holder.data?.contact_lookup : enrichment.lookup
  const [upgrade, setUpgrade] = useState(false)
  const status = actions.status ?? item?.status ?? 'new'
  const clock = item ? signalClock(item, locale) : null
  const companyHref = item?.company_key ? `/app/companies/${encodeURIComponent(item.company_key)}${location.search}` : null
  const contactWall = item?.landing_example_holder
    ? `${fr ? 'Comme pour' : 'As with'} ${item.landing_example_holder} : ${fr ? 'dirigeant, téléphone, e-mail, historique des marchés.' : 'director, phone, email and contract history.'}`
    : undefined
  const action = (next: 'new' | 'saved' | 'ignored' | 'contacted') => { void actions.setStatus(next).catch(() => {}) }
  const busy = enrichment.state === 'requesting' || enrichment.state === 'polling'
  const enrichFeedback = <>
    <CompanyEnrichmentStatus enrichment={enrichment.directoryEnrichment} />
    {enrichment.state === 'waiting' && <button className={styles.textButton} onClick={() => void enrichment.refresh()}>{fr ? 'Actualiser le résultat' : 'Refresh result'}</button>}
    {busy && <p className={styles.caption} role="status">{fr ? 'Recherche en cours…' : 'Research in progress…'}</p>}
    {(enrichment.state === 'timeout' || enrichment.state === 'error') && <p className={styles.error} role="alert">{fr ? 'La recherche prend plus de temps que prévu.' : 'The search is taking longer than expected.'} <button className={styles.textButton} onClick={() => void enrichment.refresh()}>{fr ? 'Vérifier le résultat' : 'Check result'}</button></p>}
    {lookup?.state === 'quota_exhausted' && <p className={styles.caption}>{fr ? 'Vos recherches sont utilisées pour cette période.' : 'Your searches have been used for this period.'}{lookup.next_reset_at && <> {fr ? 'Renouvellement le' : 'Renews on'} {date(lookup.next_reset_at)}</>}</p>}
    {lookup?.state === 'no_contact' && <p className={styles.caption}>{fr ? 'Ajoutez votre interlocuteur dans la fiche entreprise pour poursuivre votre suivi.' : 'Add your contact in the company profile to continue following up.'}</p>}
  </>
  return <DetailFrame title={fr ? 'Détail du signal' : 'Signal details'} onClose={onClose}
    badge={item ? <div className={styles.rowTop}><span className={styles.tag} data-status={status}>{statusLabel(status, fr)}</span>{clock?.value && <span>{clock.label} {date(clock.value)}</span>}</div> : undefined}
    footer={item ? <>
      <div className={styles.actions}><button className={styles.button} disabled={actions.pending} onClick={() => action(status === 'saved' ? 'new' : 'saved')}><Bookmark aria-hidden="true" />{status === 'saved' ? (fr ? 'Retirer des sauvegardés' : 'Unsave') : (fr ? 'Sauvegarder' : 'Save')}</button>
        <button className={styles.textButton} disabled={actions.pending} onClick={() => action(status === 'ignored' ? 'new' : 'ignored')}>{status === 'ignored' ? (fr ? 'Rétablir' : 'Restore') : (fr ? 'Ignorer' : 'Ignore')}</button></div>
      <button className={styles.primary} disabled={actions.pending} onClick={() => action(status === 'contacted' ? 'new' : 'contacted')}>{status === 'contacted' ? <RotateCcw aria-hidden="true" /> : <Check aria-hidden="true" />}{status === 'contacted' ? (fr ? 'Rétablir comme nouveau' : 'Mark as new') : (fr ? 'Marquer contacté' : 'Mark as contacted')}</button>
    </> : undefined}>
    {resource.loading && <p className={styles.loading} role="status">{fr ? 'Chargement du signal…' : 'Loading signal…'}</p>}
    {resource.error != null && <div className={styles.error} role="alert"><p>{fr ? 'Ce signal ne peut pas être ouvert pour le moment.' : 'This signal cannot be opened right now.'}</p><button className={styles.button} onClick={resource.reload}>{fr ? 'Réessayer' : 'Retry'}</button></div>}
    {detail?.locked && <section className={styles.empty}><h2>{fr ? 'Un marché pour votre prospection' : 'A contract for your prospecting'}</h2><p>{detail.headline}</p>{detail.landing_example_holder && <p>{fr ? `Comme pour ${detail.landing_example_holder} : dirigeant, téléphone, e-mail, historique des marchés.` : `As with ${detail.landing_example_holder}: director, phone, email and contract history.`}</p>}<button onClick={() => setUpgrade(true)} className={styles.primary}>{fr ? 'Voir ce contact — 49 €/mois' : 'View this contact — €49/month'}</button></section>}
    {item && <SignalContent item={item} holder={<HolderSummary name={item.company.name ?? (fr ? 'Titulaire du marché' : 'Contract holder')} href={item.landing_demo ? null : companyHref}
      directory={item.landing_directory ?? holderProfile?.directory} loading={!item.landing_demo && holder.loading && !!item.company_key} contacts={[
        ...(item.notice_facts?.contacts_locked ? [] : item.notice_facts?.contacts ?? []),
        ...(holderProfile?.capabilities.can_view_company_data && !holderProfile.contacts_locked ? holderProfile.public_contacts ?? [] : []),
      ]}
      lockedFields={item.landing_demo ? [] : [...(item.notice_facts?.contacts_locked ? item.notice_facts.available_contact_fields : []), ...(holderProfile?.contacts_locked ? holderProfile.available_contact_fields ?? [] : []), ...(!holderProfile?.capabilities.can_view_company_data && holderProfile && 'available_fields' in holderProfile ? holderProfile.available_fields ?? [] : [])]} lookup={item.landing_demo ? null : lookup}
      onOpenCompany={!item.landing_demo && companyHref ? () => navigate(companyHref) : undefined} onUpgrade={() => setUpgrade(true)}
      claimRequired={Boolean(me.temporary_access && !item.locked)} onClaimAccess={() => navigate('/app/create-access', { state: { returnTo: `${location.pathname}${location.search}` } })}
      onLookup={holderProfile?.capabilities.can_lookup_contact ? () => { void enrichment.startLookup().catch(() => {}) } : undefined}
      onEnrich={holderProfile?.capabilities.can_enrich_company ? () => { void enrichment.startEnrichment().catch(() => {}) } : undefined} pending={busy} feedback={item.landing_demo ? undefined : enrichFeedback} lockedMessage={contactWall} />}
      notes={<NotesField store={p.noteStore} identity={{ accountId: p.accountId, kind: 'signal', entityId: item.signal_id }} />} />}
    {actions.error != null && <p className={styles.error} role="alert">{actions.conflict ? (fr ? 'Le statut a changé dans une autre fenêtre.' : 'The status changed in another window.') : (fr ? 'Le statut n’a pas pu être enregistré.' : 'The status could not be saved.')} <button className={styles.textButton} onClick={actions.reload}>{fr ? 'Actualiser' : 'Refresh'}</button></p>}
    {upgrade && <UpgradeDialog onClose={() => setUpgrade(false)} intent={{ kind: 'signal', signalKey, ...(artifact ? { artifactId: artifact } : {}) }} planCode={detail?.landing_example_holder ? 'essential' : undefined} />}
  </DetailFrame>
}
