import { useParams } from 'react-router-dom'
import { CompaniesPage } from './CompaniesPage'

/** Existing /directory/:siren links share the table and dossier without inventing a company key. */
export function DirectoryCompanyPage() {
  const { directorySiren } = useParams()
  return <CompaniesPage directorySiren={directorySiren} />
}
