import { Link } from 'react-router-dom'
import { ArrowRight, LockKeyhole } from 'lucide-react'
import type { CompanyListItem, DirectorySearchPage } from '../../api/types'
import { useI18n } from '../../i18n'
import { initials } from '../adapters'
import styles from '../Prospecting.module.css'

export type CompanyTableItem = CompanyListItem | DirectorySearchPage['items'][number]
export function CompanyListRow({ item, search, returnTo }: { item: CompanyTableItem; search: string; returnTo: string }) {
  const { locale, number } = useI18n()
  const fr = locale === 'fr'
  const directory = 'directory' in item ? item.directory : null
  const params = new URLSearchParams(search)
  if (directory) params.set('view', 'directory')
  const href = `/app/companies/${encodeURIComponent(item.company_key)}${params.size ? `?${params}` : ''}`
  const state = { returnToCompaniesList: returnTo }
  const contactKnown = directory && !directory.fields_locked && (directory.phone || directory.published_email)
  const locked = directory?.fields_locked && (directory.available_fields?.length ?? 0) > 0
  const status = 'contact_status' in item ? item.contact_status : null
  const labels = { to_contact: fr ? 'À contacter' : 'To contact', contacted: fr ? 'Contactée' : 'Contacted', replied: fr ? 'A répondu' : 'Replied' }
  return <tr>
    <td><div className={styles.companyCell}><span className={styles.avatar} aria-hidden="true">{initials(item.name)}</span><div>
      <Link className={styles.companyName} to={href} state={state}>{item.name}</Link>
      <span className={styles.caption}>{directory?.naf_label ?? directory?.family_labels?.join(' · ') ?? ('origin' in item && item.origin === 'user' ? fr ? 'Entreprise ajoutée à votre prospection' : 'Added to your prospects' : fr ? 'Issue de vos publications' : 'From your publications')}</span>
    </div></div></td>
    <td>{item.city ?? (fr ? 'Ville non renseignée' : 'City not provided')}<span className={styles.caption}>{directory
      ? `${fr ? 'Siège' : 'Office'} · ${directory.department ?? item.country ?? ''}`
      : 'awards_count' in item ? `${number(item.awards_count)} ${fr ? 'publications liées' : 'related publications'}` : ''}</span></td>
    <td>{locked ? <span className={styles.caption}><LockKeyhole aria-hidden="true" />{fr ? 'Fiche enrichie' : 'Enriched profile'}</span>
      : contactKnown ? fr ? 'Coordonnées disponibles' : 'Contact details available'
        : directory?.website_url && !directory.fields_locked ? fr ? 'Site identifié' : 'Website available'
          : <Link className={styles.textButton} to={href} state={state}>{fr ? 'Voir le dossier' : 'View dossier'}</Link>}</td>
    <td>{status ? <span className={styles.tag} data-status={status}>{labels[status]}</span>
      : <span className={styles.caption}>{item.tracked ? fr ? 'Dans ma prospection' : 'In my prospects' : fr ? 'Hors prospection' : 'Not tracked'}</span>}</td>
    <td><Link className={styles.iconButton} to={href} state={state} aria-label={fr ? `Ouvrir le dossier de ${item.name}` : `Open dossier for ${item.name}`}><ArrowRight aria-hidden="true" /></Link></td>
  </tr>
}

export function CompanyTable({ items, search, returnTo }: { items: CompanyTableItem[]; search: string; returnTo: string }) {
  const { locale } = useI18n()
  const fr = locale === 'fr'
  return <table className={styles.table} aria-label={fr ? 'Entreprises' : 'Companies'}><thead><tr>
    <th scope="col">{fr ? 'Entreprise' : 'Company'}</th><th scope="col">{fr ? 'Repères' : 'Overview'}</th><th scope="col">Contact</th><th scope="col">{fr ? 'Suivi' : 'Follow-up'}</th><th scope="col"><span className={styles.srOnly}>Dossier</span></th>
  </tr></thead><tbody>{items.map((item) => <CompanyListRow key={item.company_key} item={item} search={search} returnTo={returnTo} />)}</tbody></table>
}
