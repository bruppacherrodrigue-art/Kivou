import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, LockKeyhole } from 'lucide-react'
import type { CompanyContactLookup, DirectoryCompany } from '../../api/types'
import { useI18n } from '../../i18n'
import { safeExternal } from '../adapters'
import type { NoticeContact } from '../models'
import { DirectoryContactFacts, PublicContactFacts, distinctPublicContacts, usableEmail, usablePhone } from './PublicContactFacts'
import styles from '../Prospecting.module.css'

export function HolderSummary({ name, href, directory, contacts = [], lookup, lockedFields = [], loading = false,
  onOpenCompany, onUpgrade, onLookup, onEnrich, pending = false, feedback, lockedMessage,
}: {
  name: string; href?: string | null; directory?: DirectoryCompany | null; contacts?: NoticeContact[];
  lookup?: CompanyContactLookup | null; lockedFields?: string[]; loading?: boolean;
  onOpenCompany?: () => void; onUpgrade?: () => void; onLookup?: () => void; onEnrich?: () => void;
  pending?: boolean; feedback?: ReactNode; lockedMessage?: string;
}) {
  const { locale, date, number } = useI18n()
  const fr = locale === 'fr'
  const phone = !directory?.fields_locked && (usablePhone(directory?.phone) || usablePhone(lookup?.organization?.phone))
  const email = !directory?.fields_locked && usableEmail(directory?.published_email)
  const website = !directory?.fields_locked && (safeExternal(directory?.website_url) || safeExternal(lookup?.organization?.website_url))
  const people = lookup?.state === 'ready' ? lookup.contacts?.filter((person) => person.email_status === 'verified' && usableEmail(person.email)) ?? [] : []
  const sourceContacts = distinctPublicContacts(contacts)
  const available = [...new Set([...(directory?.fields_locked ? directory.available_fields ?? [] : []), ...lockedFields])]
  const workforce = directory?.workforce
  const director = directory?.director_display_name
    ? { name: directory.director_display_name, title: directory.director_display_title }
    : directory?.directors?.[0]
  const hasData = !!(phone || email || website || director || sourceContacts.length || people.length)
  const employees = workforce ? workforce.precision === 'range' && workforce.minimum !== null
    ? `${number(workforce.minimum)}–${number(workforce.maximum)} ${fr ? 'salariés' : 'employees'}`
    : `${fr ? 'Environ' : 'About'} ${number(workforce.maximum)} ${fr ? 'salariés' : 'employees'}` : null
  const fieldLabel = (field: string) => ({ phone: fr ? 'téléphone' : 'phone', email: fr ? 'e-mail' : 'email', website: fr ? 'site internet' : 'website', workforce: fr ? 'effectif' : 'workforce', directors: fr ? 'dirigeants' : 'directors' })[field] ?? field
  return <section className={styles.holder} aria-label={fr ? 'Titulaire' : 'Award holder'}>
    <div className={styles.kicker}>{fr ? 'Titulaire' : 'Award holder'}</div>
    <div className={styles.holderHead}>
      {href ? <Link className={styles.holderName} to={href}>{name}</Link> : <span className={styles.holderName}>{name}</span>}
      {href && <Link className={styles.textButton} to={href}>{fr ? 'Voir la fiche' : 'Company profile'} <ArrowRight aria-hidden="true" /></Link>}
    </div>
    {(directory?.naf_label || directory?.city || employees) && <p className={styles.holderSub}>{[directory?.naf_label, directory?.city, employees].filter(Boolean).join(' · ')}</p>}
    {loading && <p className={styles.muted} role="status">{fr ? 'Chargement des données entreprise…' : 'Loading company data…'}</p>}
    {(phone || email || website) && <DirectoryContactFacts directory={directory} lookup={lookup} />}
    {director && <p className={styles.holderSub}><strong>{fr ? 'Dirigeant' : 'Director'} :</strong> {director.name}{director.title ? ` · ${director.title}` : ''}</p>}
    <PublicContactFacts contacts={sourceContacts} />
    {people.map((person) => <div key={person.email} className={styles.guide}><strong>{person.name}</strong><span className={styles.caption}>{person.title}</span><a className={styles.textButton} href={`mailto:${person.email}`}>{person.email}</a><small className={styles.caption}>{fr ? 'E-mail nominatif vérifié' : 'Verified personal business email'}</small></div>)}
    {available.length > 0 && <div className={styles.lockedData}>
      <div className={styles.lockedLines} aria-hidden="true">{available.map((field) => <span key={field} />)}</div>
      <p className={styles.muted}>{lockedMessage ?? <>{fr ? 'Données disponibles : ' : 'Available data: '}{available.map(fieldLabel).join(' · ')}</>}</p>
      {onUpgrade && <button className={styles.soft} onClick={onUpgrade}><LockKeyhole aria-hidden="true" />{fr ? 'Voir les offres — 49 €/mois' : 'View plans — €49/month'}</button>}
    </div>}
    {!loading && !hasData && available.length === 0 && <div className={styles.guide}>
      <h4>{fr ? 'Trouver le bon interlocuteur' : 'Find the right contact'}</h4>
      <p>{fr ? 'Complétez les coordonnées de cette entreprise pour préparer votre premier échange.' : 'Complete this company’s contact details to prepare your first conversation.'}</p>
      {onEnrich ? <button className={styles.soft} disabled={pending} onClick={onEnrich}>{fr ? 'Enrichir la fiche entreprise' : 'Enrich company profile'}</button>
        : onOpenCompany ? <button className={styles.soft} onClick={onOpenCompany}>{fr ? 'Compléter la fiche entreprise' : 'Complete company profile'}</button>
          : href ? <Link className={styles.soft} to={href}>{fr ? 'Compléter la fiche entreprise' : 'Complete company profile'}</Link> : null}
    </div>}
    {onLookup && lookup && (lookup.state === 'available' || lookup.state === 'ready' && lookup.can_refresh) && <div className={styles.guide}>
      <button className={styles.textButton} onClick={onLookup} disabled={pending}>{fr ? 'Trouver le décideur' : 'Find the decision maker'} <ArrowRight aria-hidden="true" /></button>
      <p>{fr ? 'E-mail nominatif vérifié' : 'Verified business email'} · {number(lookup.remaining)} {fr ? 'recherches restantes' : 'searches remaining'}</p>
    </div>}
    {hasData && onEnrich && <button className={styles.textButton} disabled={pending} onClick={onEnrich}>{fr ? 'Actualiser les données entreprise' : 'Refresh company data'}</button>}
    {directory?.register_observed_at && <p className={styles.caption}>{fr ? 'Registre national des entreprises' : 'National business register'} · {date(directory.register_observed_at)}</p>}
    {feedback}
  </section>
}
