import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ArrowRight, Bookmark, Check, ExternalLink, LockKeyhole } from 'lucide-react'
import { ApiError } from '../../api/client'
import { companies } from '../../api/endpoints'
import type { CompanyContactStatus, CompanyDossierResponse, DirectoryCompany } from '../../api/types'
import { useI18n } from '../../i18n'
import { dossierName, formatAmount, initials, safeExternal, signalClock, signalTitle } from '../adapters'
import { useProspecting, useProspectingResource } from '../ProspectingProvider'
import { signalDetailPath } from '../routeState'
import { useCompanyActions } from '../useCompanyActions'
import { useCompanyEnrichment } from '../useCompanyEnrichment'
import { DetailFrame } from './DetailFrame'
import { NotesField } from './NotesField'
import { UserContactForm } from './UserContactForm'
import { ContactFacts, DirectoryContactFacts, PublicContactFacts } from './PublicContactFacts'
import { CompanyEnrichmentStatus } from './CompanyEnrichmentStatus'
import styles from '../Prospecting.module.css'

export function CompanyDossier({ companyKey, directorySiren, onClose, onUpgrade }: {
  companyKey?: string
  directorySiren?: string
  onClose: () => void
  onUpgrade?: (addressedKey: string) => void
}) {
  const { locale } = useI18n()
  const fr = locale === 'fr'
  const resource = useProspectingResource('company-dossier', (signal) => companyKey
    ? companies.dossier(companyKey, { signal }) : companies.directoryGet(directorySiren!, { signal }),
  { companyKey: companyKey ?? null, directorySiren: directorySiren ?? null }, !!(companyKey || directorySiren), { scopeIndependent: true })
  if (resource.data) return <LoadedCompanyDossier key={companyKey ?? directorySiren} profile={resource.data} addressedKey={companyKey ?? resource.data.company_key} onClose={onClose} onUpgrade={onUpgrade} />
  const missing = resource.error instanceof ApiError && resource.error.status === 404
  return <DetailFrame title={fr ? 'Dossier entreprise' : 'Company dossier'} onClose={onClose}>
    {resource.error ? <div className={styles.error} role="alert">
      <p>{missing ? fr ? 'Cette entreprise n’est plus accessible.' : 'This company is no longer accessible.' : fr ? 'Le dossier n’a pas pu être chargé.' : 'The dossier could not be loaded.'}</p>
      <button className={styles.button} onClick={resource.reload}>{fr ? 'Réessayer' : 'Retry'}</button>
    </div> : <p className={styles.loading} role="status">{fr ? 'Chargement du dossier…' : 'Loading dossier…'}</p>}
  </DetailFrame>
}

function LoadedCompanyDossier({ profile: initialProfile, addressedKey, onClose, onUpgrade }: {
  profile: CompanyDossierResponse; addressedKey: string; onClose: () => void; onUpgrade?: (addressedKey: string) => void
}) {
  const { locale, shortDate, number } = useI18n()
  const fr = locale === 'fr'
  const location = useLocation()
  const { accountId, noteStore } = useProspecting()
  const binding = { company_key: addressedKey, private_subject_key: initialProfile.private_subject_key, capabilities: initialProfile.capabilities }
  const actions = useCompanyActions(binding)
  const enrichment = useCompanyEnrichment(binding, { initialLookup: initialProfile.contact_lookup, initialDirectoryEnrichment: initialProfile.directory_enrichment })
  const profile = enrichment.dossier ?? initialProfile
  const [editingContact, setEditingContact] = useState(false)
  const name = dossierName(profile)
  const directory = profile.directory
  const publicData = profile.capabilities.can_view_company_data && !directory?.fields_locked
  const contact = profile.manual_contact.contact
  const status = profile.contact_status ?? 'to_contact'
  const statuses: Record<CompanyContactStatus, string> = { to_contact: fr ? 'À contacter' : 'To contact', contacted: fr ? 'Contactée' : 'Contacted', replied: fr ? 'A répondu' : 'Replied' }
  const nextStatus: CompanyContactStatus = status === 'to_contact' ? 'contacted' : status === 'contacted' ? 'replied' : 'to_contact'
  const nextLabel = status === 'to_contact' ? fr ? 'Marquer comme contactée' : 'Mark contacted' : status === 'contacted' ? fr ? 'Marquer une réponse' : 'Mark replied' : fr ? 'Repasser à contacter' : 'Mark to contact'
  const busy = actions.pending !== null
  // A rejected refresh may revoke previously shown Apollo data; never fall back to it.
  const lookup = enrichment.state === 'idle' ? profile.contact_lookup : enrichment.lookup
  const lookupBusy = enrichment.state === 'requesting' || enrichment.state === 'polling'
  const related = 'signals' in profile ? profile.signals : []
  const markets = 'markets' in profile ? profile.markets : []
  const available = [...new Set([
    ...(profile.contacts_locked ? profile.available_contact_fields ?? [] : []),
    ...(directory?.fields_locked ? directory.available_fields ?? [] : []),
    ...(!profile.capabilities.can_view_company_data && 'available_fields' in profile ? profile.available_fields ?? [] : []),
  ])].filter((field) => ['phone', 'email', 'website', 'workforce', 'directors'].includes(field))
  const fields: Record<string, string> = {
    phone: fr ? 'Téléphone' : 'Phone', email: fr ? 'Email' : 'Email', website: fr ? 'Site internet' : 'Website', workforce: fr ? 'Effectif' : 'Workforce', directors: fr ? 'Dirigeants' : 'Directors',
  }
  const footer = profile.membership.tracked ? <>
    <span className={styles.muted}>{fr ? 'Votre suivi, à votre rythme' : 'Your follow-up, at your pace'}</span>
    {profile.capabilities.can_follow_company && <button className={styles.primary} disabled={busy} onClick={() => void actions.setContactStatus(nextStatus).catch(() => {})}><Check aria-hidden="true" />{nextLabel}</button>}
  </> : <>
    <span className={styles.muted}>{fr ? 'Gardez cette entreprise à portée de main' : 'Keep this company within reach'}</span>
    {profile.capabilities.can_follow_company && <button className={styles.primary} disabled={busy || !profile.private_subject_key} onClick={() => void actions.follow().catch(() => {})}><Bookmark aria-hidden="true" />{fr ? 'Ajouter à ma prospection' : 'Add to my prospects'}</button>}
  </>
  return <DetailFrame title={fr ? 'Dossier entreprise' : 'Company dossier'} onClose={onClose} footer={editingContact ? undefined : footer}>
    <div className={styles.companyCell}><span className={styles.avatar} aria-hidden="true">{initials(name)}</span><div>
      <h2 className={styles.detailTitle}>{name}</h2>
      <p className={styles.detailMeta}>{'official_identity' in profile ? profile.official_identity.identifiers.map((id) => `${id.scheme} ${id.value}`).join(' · ') : `SIREN ${profile.directory.siren}`}</p>
    </div></div>
    {editingContact ? <UserContactForm key={profile.private_subject_key} company={binding} initial={profile.manual_contact} onCancel={() => setEditingContact(false)} onSaved={() => setEditingContact(false)} /> : <>
      <div className={styles.toolbar}>
        <span className={styles.muted}>{fr ? 'Votre suivi commercial' : 'Your commercial follow-up'}</span>
        {profile.membership.tracked ? <select aria-label={fr ? `Statut commercial de ${name}` : `Commercial status of ${name}`} value={status} disabled={busy || !profile.capabilities.can_follow_company} onChange={(event) => { if (event.target.value !== status) void actions.setContactStatus(event.target.value as CompanyContactStatus).catch(() => {}) }}>
          {Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select> : <span className={styles.tag}>{fr ? 'Hors de ma prospection' : 'Not in my prospects'}</span>}
      </div>
      {actions.error && <p className={styles.error} role="alert">{fr ? 'L’action n’a pas été confirmée. Réessayez.' : 'The action was not confirmed. Please retry.'}</p>}
      {profile.identity_resolution === 'isolated' && <p className={styles.muted}>{fr ? 'Votre suivi et vos notes restent rattachés à cette identité distincte.' : 'Your follow-up and notes remain attached to this distinct identity.'}</p>}
      <section className={styles.detailSection}><h3>{fr ? 'Contacts' : 'Contacts'}</h3>
        {contact && <div className={styles.guide}>
          <strong>{contact.name}</strong><span className={styles.caption}>{fr ? 'Ajouté par vous' : 'Added by you'}{contact.role ? ` · ${contact.role}` : ''}</span>
          <ContactFacts email={contact.email} phone={contact.phone} />
        </div>}
        {available.length > 0 && <div className={styles.lockedData}>
          {available.map((field) => <div key={field}><span className={styles.caption}>{fields[field]} {fr ? 'disponible dans la fiche enrichie' : 'available in the enriched profile'}</span><div className={styles.lockedLines} aria-hidden="true"><span /></div></div>)}
          {onUpgrade ? <button className={styles.soft} onClick={() => onUpgrade(addressedKey)}><LockKeyhole aria-hidden="true" />{fr ? 'Débloquer la fiche' : 'Unlock company profile'}</button>
            : <Link className={styles.soft} to="/app/billing"><LockKeyhole aria-hidden="true" />{fr ? 'Débloquer la fiche' : 'Unlock company profile'}</Link>}
        </div>}
        {profile.capabilities.can_view_company_data && !profile.contacts_locked && <PublicContactFacts contacts={profile.public_contacts ?? []} />}
        {publicData && <>
          <DirectoryContactFacts directory={directory} lookup={lookup} officialWebsite={'official_identity' in profile ? profile.official_identity.website_url : null} />
          {lookup?.state === 'ready' && lookup.contacts?.filter((person) => person.email_status === 'verified').map((person) => <div className={styles.guide} key={person.email}><strong>{person.name}</strong><span className={styles.caption}>{person.title}</span><ContactFacts email={person.email} source={fr ? 'Email nominatif vérifié · Apollo' : 'Verified business email · Apollo'} /></div>)}
        </>}
        <div className={styles.guide}>
          {!contact && <p>{fr ? 'Renseignez l’interlocuteur que vous connaissez pour préparer votre prochaine conversation.' : 'Add the contact you know to prepare your next conversation.'}</p>}
          {profile.capabilities.can_manage_personal_contact && profile.private_subject_key && <button className={styles.button} onClick={() => setEditingContact(true)}>{contact ? fr ? 'Modifier mon contact' : 'Edit my contact' : fr ? 'Ajouter un contact' : 'Add a contact'}</button>}
        </div>
        <div className={styles.actions}>
          {profile.capabilities.can_enrich_company && <button className={styles.textButton} disabled={lookupBusy} onClick={() => void enrichment.startEnrichment().catch(() => {})}>{fr ? 'Compléter la fiche entreprise' : 'Enrich company profile'}</button>}
          {profile.capabilities.can_lookup_contact && lookup && (lookup.state === 'available' || lookup.state === 'ready' && lookup.can_refresh) && <button className={styles.textButton} disabled={lookupBusy} onClick={() => void enrichment.startLookup().catch(() => {})}>{fr ? 'Rechercher un contact' : 'Find a contact'}</button>}
        </div>
        {lookup && <p className={styles.caption}>{number(lookup.remaining)} {fr ? 'recherches de contacts restantes ce mois-ci' : 'contact searches remaining this month'}</p>}
        {lookupBusy && <p role="status" className={styles.muted}>{fr ? 'Recherche en cours…' : 'Researching…'}</p>}
        <CompanyEnrichmentStatus enrichment={enrichment.directoryEnrichment} />
        {enrichment.state === 'waiting' && <button className={styles.textButton} onClick={() => void enrichment.refresh()}>{fr ? 'Actualiser le résultat' : 'Refresh result'}</button>}
        {(enrichment.state === 'timeout' || enrichment.state === 'error') && <div className={styles.error} role="status"><p>{fr ? 'Le résultat n’est pas encore confirmé. Vous pouvez actualiser sans lancer une nouvelle recherche.' : 'The result is not yet confirmed. Refresh without starting another search.'}</p><button className={styles.button} onClick={() => void enrichment.refresh()}>{fr ? 'Actualiser le résultat' : 'Refresh result'}</button></div>}
        {lookup?.state === 'no_contact' && <p className={styles.muted}>{fr ? 'Aucun contact vérifié n’a été trouvé.' : 'No verified contact was found.'}</p>}
        {lookup?.state === 'quota_exhausted' && <p className={styles.muted}>{fr ? 'Votre quota de recherches est épuisé.' : 'Your search quota is exhausted.'}</p>}
        {lookup?.state === 'identity_unavailable' && <p className={styles.muted}>{fr ? 'L’identité annuaire ne permet pas encore de lancer cette recherche.' : 'The directory identity does not yet support this search.'}</p>}
        {lookup?.state === 'failed' && <p className={styles.muted}>{fr ? 'La recherche de contact n’a pas abouti.' : 'Contact research did not succeed.'}</p>}
        {lookup?.next_reset_at && lookup.remaining === 0 && <p className={styles.caption}>{fr ? 'Reprise du quota le' : 'Quota resets on'} {shortDate(lookup.next_reset_at)}</p>}
        {lookup?.researched_at && <p className={styles.caption}>{fr ? 'Recherche Apollo du' : 'Apollo research from'} {shortDate(lookup.researched_at)}</p>}
        {lookup && publicData && <Link className={styles.textButton} to={lookup.removal_path}>{fr ? 'Signaler ou retirer une donnée de contact' : 'Report or remove contact data'}</Link>}
      </section>
      <section className={styles.detailSection}><h3>{fr ? 'Repères entreprise' : 'Company facts'}</h3>
        <dl className={styles.facts}>
          {directory?.naf_label && <div><dt>{fr ? 'Activité au registre' : 'Registered activity'}</dt><dd>{directory.naf_label}{directory.naf_code ? ` · ${directory.naf_code}` : ''}</dd></div>}
          {(directory?.city || 'official_identity' in profile && profile.official_identity.address) && <div><dt>{fr ? 'Siège enregistré' : 'Registered office'}</dt><dd>{directory?.city ?? ('official_identity' in profile ? profile.official_identity.address : '')}</dd></div>}
          {publicData && directory?.workforce && <div><dt>{fr ? 'Effectif indicatif' : 'Indicative workforce'}</dt><dd>{workforceLabel(directory.workforce, fr)}</dd></div>}
        </dl>
        {publicData && !!directory?.directors?.length && <details><summary>{fr ? 'Dirigeants au registre' : 'Registered directors'} · {directory.directors.length}</summary>{directory.directors.map((director, index) => <p key={`${director.name}-${index}`}>{director.name}{director.title ? ` · ${director.title}` : ''}</p>)}</details>}
        {directory?.register_observed_at && <p className={styles.caption}>{fr ? 'Registre consulté le' : 'Register consulted on'} {shortDate(directory.register_observed_at)}</p>}
      </section>
      {(related.length > 0 || markets.length > 0) && <section className={styles.detailSection}><h3>{fr ? 'Publications liées' : 'Related publications'}</h3>
        {related.map((signal) => {
          const search = new URLSearchParams(location.search)
          search.delete('presentation_artifact_id')
          if (signal.presentation?.artifact_id) search.set('presentation_artifact_id', signal.presentation.artifact_id)
          const clock = signalClock(signal, locale)
          return <Link key={signal.signal_id} className={styles.signalRow} to={signalDetailPath(signal.signal_id, search.toString())} state={{ returnToCompany: `${location.pathname}${location.search}` }}>
            <div className={styles.rowMain}><strong>{signalTitle(signal)}</strong><span className={styles.caption}>{clock.label} {clock.value ? shortDate(clock.value) : '—'}{signal.contract.amount ? ` · ${formatAmount(signal.contract.amount, locale)}` : ''}</span></div><ArrowRight aria-hidden="true" />
          </Link>
        })}
        {markets.map((market) => { const href = safeExternal(market.source_url); return <div className={styles.signalRow} key={market.market_id}>
          <div className={styles.rowMain}>{href ? <a className={styles.companyName} href={href} target="_blank" rel="noopener noreferrer">{market.title ?? (fr ? 'Publication de marché public' : 'Public award publication')} <ExternalLink aria-hidden="true" /></a> : <strong>{market.title ?? (fr ? 'Publication de marché public' : 'Public award publication')}</strong>}
            <span className={styles.caption}>{[market.date ? shortDate(market.date) : null, formatAmount(market.amount, locale), market.buyers?.join(' · ')].filter(Boolean).join(' · ')}</span>
          </div>
        </div> })}
      </section>}
      {profile.capabilities.can_take_notes && profile.private_subject_key && <NotesField store={noteStore} identity={{ accountId, kind: 'company', entityId: profile.private_subject_key, addressKey: addressedKey }} />}
      {!!profile.history?.length && <section className={styles.detailSection}><h3>{fr ? 'Historique du suivi' : 'Follow-up history'}</h3><ul>{profile.history.map((entry, index) => <li key={`${entry.occurred_at}-${index}`}>{shortDate(entry.occurred_at)} · {entry.type in statuses ? statuses[entry.type as CompanyContactStatus] : entry.type === 'note' ? fr ? 'Note mise à jour' : 'Note updated' : fr ? 'Action sur un signal lié' : 'Related signal action'}</li>)}</ul></section>}
    </>}
  </DetailFrame>
}

function workforceLabel(workforce: NonNullable<DirectoryCompany['workforce']>, fr: boolean) {
  const unit = fr ? 'salariés' : 'employees'
  return workforce.precision === 'range' ? workforce.minimum === null
    ? `${fr ? 'Jusqu’à' : 'Up to'} ${workforce.maximum} ${unit}` : `${workforce.minimum}–${workforce.maximum} ${unit}`
    : `${fr ? 'Environ' : 'About'} ${workforce.maximum} ${unit}`
}
