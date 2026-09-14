import type { DirectorySearchPage } from '../../api/types'
import { useI18n } from '../../i18n'
import { CompanyTable } from './CompanyListRow'
import styles from '../Prospecting.module.css'

export function DirectoryResults({ items, search, returnTo }: { items: DirectorySearchPage['items']; search: string; returnTo: string }) {
  const { locale } = useI18n()
  if (!items.length) return <div className={styles.empty}><h2>{locale === 'fr' ? 'Aucune entreprise avec ces critères.' : 'No companies match these criteria.'}</h2><p>{locale === 'fr' ? 'Élargissez la recherche dans l’annuaire sans modifier votre profil cible.' : 'Broaden your directory search without changing your target profile.'}</p></div>
  return <CompanyTable items={items} search={search} returnTo={returnTo} />
}
