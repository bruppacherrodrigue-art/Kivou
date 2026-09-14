import type { CompanyDirectoryEnrichment } from '../../api/types'
import { useI18n } from '../../i18n'
import styles from '../Prospecting.module.css'

/** A completed research pass may add nothing; only persisted additions are announced. */
export function CompanyEnrichmentStatus({ enrichment }: { enrichment?: CompanyDirectoryEnrichment | null }) {
  const { locale, date } = useI18n()
  if (!enrichment || ['available', 'locked', 'identity_unavailable'].includes(enrichment.state)) return null
  const fr = locale === 'fr'
  let message = ''
  if (enrichment.state === 'queued') message = fr ? 'Enrichissement demandé. Le traitement continue même si vous fermez ce dossier.' : 'Enrichment requested. Processing continues when you close this dossier.'
  else if (enrichment.state === 'running') message = fr ? 'Vérification des données entreprise en cours…' : 'Checking company data…'
  else if (enrichment.state === 'budget_wait') message = fr ? 'La demande est conservée. Le traitement reprendra dès que le budget de recherche sera disponible.' : 'Your request is saved. Processing resumes when the research budget is available.'
  else if (enrichment.state === 'failed') message = fr ? 'L’enrichissement n’a pas abouti. Les données déjà connues sont conservées.' : 'Enrichment did not finish. Previously known data is preserved.'
  else if (enrichment.outcome === 'no_change') message = fr ? 'Recherche terminée : aucune coordonnée supplémentaire confirmée.' : 'Research completed: no additional contact details confirmed.'
  else if (enrichment.outcome === 'enriched' && enrichment.added_fields.length) {
    const labels = { website: fr ? 'site internet' : 'website', phone: fr ? 'téléphone' : 'phone', email: fr ? 'e-mail public' : 'public email' }
    message = `${fr ? 'Données ajoutées' : 'Added details'} : ${enrichment.added_fields.map((field) => labels[field]).join(', ')}.`
  } else if (enrichment.outcome === 'enriched') message = fr ? 'Recherche terminée : coordonnées mises à jour.' : 'Research completed: contact details updated.'
  else if (enrichment.state === 'ready') message = fr ? 'Les données entreprise sont à jour.' : 'Company data is current.'
  else message = fr ? 'Recherche terminée. Certaines coordonnées restent à compléter.' : 'Research completed. Some contact details remain missing.'
  return <p className={styles.caption} role="status">{message}{enrichment.retry_after && enrichment.state === 'budget_wait' && <> {fr ? 'Reprise prévue le' : 'Expected to resume on'} {date(enrichment.retry_after)}.</>}</p>
}
