import type { ReactNode } from 'react'
import { ExternalLink } from 'lucide-react'
import type { CompanyContactLookup, CompanyPublicContact, DirectoryCompany } from '../../api/types'
import { useI18n } from '../../i18n'
import { safeExternal } from '../adapters'
import styles from '../Prospecting.module.css'

export const usablePhone = (value?: string | null) => value && /^\+?[\d\s().-]+$/.test(value) && value.replace(/\D/g, '').length >= 9 && value.replace(/\D/g, '').length <= 15 ? value : null
export const usableEmail = (value?: string | null) => value && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? value : null

export function distinctPublicContacts(contacts: CompanyPublicContact[]) {
  const seen = new Set<string>()
  return contacts.filter((contact) => {
    if (!usablePhone(contact.phone) && !usableEmail(contact.email) && !safeExternal(contact.website)) return false
    const identity = contact.identifiers?.length ? contact.identifiers.map((id) => `${id.scheme.toLowerCase()}:${id.value.replace(/\s/g, '')}`).sort().join('|')
      : `${contact.source_notice_id ?? ''}:${contact.organization_ref}:${contact.organization_name}`
    const key = JSON.stringify([identity, contact.organization_name, contact.phone?.replace(/[^+\d]/g, ''), contact.email?.toLowerCase(), contact.website, contact.contact_name])
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function ContactFacts({ email, phone, website, source, emailSource, phoneSource, websiteSource }: {
  email?: string | null; phone?: string | null; website?: string | null; source?: ReactNode;
  emailSource?: ReactNode; phoneSource?: ReactNode; websiteSource?: ReactNode;
}) {
  const { locale } = useI18n()
  const validEmail = usableEmail(email)
  const validPhone = usablePhone(phone)
  const href = safeExternal(website)
  if (!validEmail && !validPhone && !href) return null
  return <dl className={styles.contactFacts}>
    {validEmail && <><dt>Email</dt><dd><a href={`mailto:${validEmail}`}>{validEmail}</a>{(emailSource || source) && <small className={styles.caption}>{emailSource ?? source}</small>}</dd></>}
    {validPhone && <><dt>{locale === 'fr' ? 'Téléphone' : 'Phone'}</dt><dd><a href={`tel:${validPhone.replace(/[^+\d]/g, '')}`}>{validPhone}</a>{(phoneSource || source) && <small className={styles.caption}>{phoneSource ?? source}</small>}</dd></>}
    {href && <><dt>{locale === 'fr' ? 'Site identifié' : 'Website'}</dt><dd><a href={href} target="_blank" rel="noopener noreferrer">{new URL(href).hostname} <ExternalLink aria-hidden="true" /></a>{(websiteSource || source) && <small className={styles.caption}>{websiteSource ?? source}</small>}</dd></>}
  </dl>
}

export function DirectoryContactFacts({ directory, lookup, officialWebsite }: {
  directory?: DirectoryCompany | null; lookup?: CompanyContactLookup | null; officialWebsite?: string | null;
}) {
  const { locale, shortDate } = useI18n()
  const fr = locale === 'fr'
  const emailSource = safeExternal(directory?.published_email_source_url)
  const sourceLabel = (source?: string) => source === 'model' ? (fr ? 'Coordonnée identifiée · à vérifier' : 'Identified contact detail · verify before use')
    : source === 'registre' ? (fr ? 'Registre national des entreprises' : 'National business register') : source
  const observed = (source: ReactNode, at?: string) => source || at ? <>{source}{at && <>{source ? ' · ' : ''}{fr ? 'Consulté le' : 'Observed on'} {shortDate(at)}</>}</> : null
  return <ContactFacts email={directory?.published_email} phone={directory?.phone ?? lookup?.organization?.phone} website={directory?.website_url ?? lookup?.organization?.website_url ?? officialWebsite}
    emailSource={observed(emailSource ? <a href={emailSource} target="_blank" rel="noopener noreferrer">{fr ? 'Publié sur le site de l’entreprise' : 'Published on the company website'}</a> : null, directory?.published_email_observed_at)}
    phoneSource={observed(directory?.phone ? sourceLabel(directory.phone_source) : lookup?.organization?.phone ? 'Apollo' : null, directory?.phone_observed_at)}
    websiteSource={observed(directory?.website_url ? sourceLabel(directory.website_source) : lookup?.organization?.website_url ? 'Apollo' : null, directory?.website_observed_at)} />
}

export function PublicContactFacts({ contacts }: { contacts: CompanyPublicContact[] }) {
  const { locale, shortDate } = useI18n()
  return <>{distinctPublicContacts(contacts).map((contact, index) => {
    const url = safeExternal(contact.source_url)
    const source = `BOAMP${contact.source_notice_id ? ` · ${contact.source_notice_id}` : ''}`
    return <div key={`${contact.source_notice_id}-${contact.organization_ref}-${index}`}>
      <p className={styles.holderSub}>{contact.organization_name}</p>
      {contact.identifiers?.length ? <p className={styles.caption}>{contact.identifiers.map((id) => `${id.scheme} ${id.value}`).join(' · ')}</p> : null}
      {contact.contact_name && <p className={styles.caption}>{contact.contact_name}</p>}
      <ContactFacts phone={contact.phone} email={contact.email} website={contact.website} />
      <p className={styles.caption}>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{source}</a> : source}{contact.observed_at && <> · {locale === 'fr' ? 'Consulté le' : 'Observed on'} {shortDate(contact.observed_at)}</>}</p>
    </div>
  })}</>
}
