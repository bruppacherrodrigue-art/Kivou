import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { Search, SlidersHorizontal } from 'lucide-react'
import { companies, type CompanyListQuery, type DirectorySearchQuery } from '../api/endpoints'
import type { CompanyContactStatus, CompanyListPage, DirectorySearchPage } from '../api/types'
import { useI18n } from '../i18n'
import { useProspecting, useProspectingResource } from '../prospecting/ProspectingProvider'
import { CompanyDossier } from '../prospecting/components/CompanyDossier'
import { CompanyTable, type CompanyTableItem } from '../prospecting/components/CompanyListRow'
import { DirectoryResults } from '../prospecting/components/DirectoryResults'
import { TargetBar } from '../prospecting/components/TargetBar'
import { UpgradeDialog } from '../prospecting/components/UpgradeDialog'
import type { CheckoutReturnIntent } from '../billing/checkoutIntent'
import { safeInternalReturn } from '../prospecting/routeState'
import styles from '../prospecting/Prospecting.module.css'

const PAGE_SIZE = 20
export function CompaniesPage({ directorySiren }: { directorySiren?: string }) {
  const { companyKey } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const { locale, number } = useI18n()
  const t = (fr: string, en: string) => locale === 'fr' ? fr : en
  const { query: scope, run, billingStatus } = useProspecting()
  const params = new URLSearchParams(location.search)
  const directoryMode = !!directorySiren || location.pathname === '/app/companies/directory' || params.get('view') === 'directory'
  const canSearch = directoryMode || billingStatus?.entitlements.filter_level === 'basic' || billingStatus?.entitlements.filter_level === 'advanced'
  const q = params.get('q') ?? ''
  const requestedStatus = params.get('contact_status')
  const status = requestedStatus && ['to_contact', 'contacted', 'replied'].includes(requestedStatus) ? requestedStatus as CompanyContactStatus : null
  const requestedSort = params.get('sort')
  const sort = directoryMode ? requestedSort === 'city' ? 'city' : 'name' : requestedSort === 'amount' ? 'amount' : 'recent'
  const department = params.get('department') ?? ''
  const family = params.get('family') ?? ''
  const [searchDraft, setSearchDraft] = useState(q)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [upgradeIntent, setUpgradeIntent] = useState<CheckoutReturnIntent | null>(null)
  const updateParams = useCallback((patch: Record<string, string | null>, mode = directoryMode) => {
    const next = new URLSearchParams(location.search)
    next.delete('cursor')
    for (const [key, value] of Object.entries(patch)) { if (value) next.set(key, value); else next.delete(key) }
    if (mode) next.set('view', 'directory'); else next.delete('view')
    navigate({ pathname: mode ? '/app/companies/directory' : '/app/companies', search: next.size ? `?${next}` : '' }, { replace: true })
  }, [location.search, directoryMode, navigate])
  useEffect(() => setSearchDraft(q), [q])
  useEffect(() => {
    if (searchDraft === q) return
    const timer = setTimeout(() => updateParams({ q: searchDraft }), 300)
    return () => clearTimeout(timer)
  }, [searchDraft, q, updateParams])
  const directoryQuery: DirectorySearchQuery = { q: q || null, department: department || null, family: family || null, sort: sort as 'name' | 'city', limit: PAGE_SIZE }
  const prospectQuery: CompanyListQuery = { ...scope, view: 'prospection', q: canSearch ? q || null : null, contact_status: status ? [status] : null, sort: sort as 'recent' | 'amount', limit: PAGE_SIZE }
  const loadPage = (signal: AbortSignal, cursor?: string | null) => directoryMode
    ? companies.directorySearch({ ...directoryQuery, cursor }, { signal }) : companies.list({ ...prospectQuery, cursor }, { signal })
  const resource = useProspectingResource<CompanyListPage | DirectorySearchPage>('companies-list', (signal) => loadPage(signal), { mode: directoryMode ? 'directory' : 'prospection', q, status, department, family, sort }, true, { scopeIndependent: directoryMode })
  const directoryOptions = useProspectingResource('directory-options', (signal) => companies.directoryOptions({ signal }), {}, directoryMode, { scopeIndependent: true })
  const [more, setMore] = useState<{ key: string; items: CompanyTableItem[]; nextCursor: string | null; loading: boolean; error: boolean; seen: string[] }>({ key: '', items: [], nextCursor: null, loading: false, error: false, seen: [] })
  const moreController = useRef<AbortController | null>(null)
  const currentKey = useRef(resource.key)
  currentKey.current = resource.key
  useEffect(() => () => { moreController.current?.abort(); moreController.current = null }, [resource.key])
  const pagination = more.key === resource.key ? more : null
  const nextCursor = pagination ? pagination.nextCursor : resource.data?.page.next_cursor ?? null
  const rows = [...new Map([...(resource.data?.items ?? []), ...(pagination?.items ?? [])].map((item) => [item.company_key, item])).values()]
  const loadMore = async () => {
    if (!nextCursor || moreController.current || pagination?.seen.includes(nextCursor)) return
    const key = resource.key
    const controller = new AbortController()
    moreController.current = controller
    const previous = pagination ?? { key, items: [], nextCursor, loading: false, error: false, seen: [] }
    setMore({ ...previous, loading: true, error: false })
    try {
      const result = await run<CompanyListPage | DirectorySearchPage>((signal) => loadPage(signal, nextCursor), controller.signal)
      if (controller.signal.aborted || currentKey.current !== key) return
      const seen = [...previous.seen, nextCursor]
      const next = result.page.has_more && !seen.includes(result.page.next_cursor ?? '') ? result.page.next_cursor : null
      setMore({ key, items: [...previous.items, ...result.items], nextCursor: next, seen, loading: false, error: false })
    } catch { if (!controller.signal.aborted && currentKey.current === key) setMore({ ...previous, loading: false, error: true }) }
    finally { if (moreController.current === controller) moreController.current = null }
  }
  const switchView = (directory: boolean) => updateParams({ q: null, sort: null, contact_status: null, department: null, family: null }, directory)
  const listPath = `${directoryMode ? '/app/companies/directory' : '/app/companies'}${location.search}`
  const closeDossier = () => {
    const state = location.state as { returnToCompaniesList?: unknown } | null
    const previous = safeInternalReturn(state?.returnToCompaniesList)
    navigate(previous?.startsWith('/app/companies') ? previous : listPath)
  }
  const counts = resource.data?.counts
  const total = directoryMode && counts && 'total' in counts ? counts.total : resource.data && 'total' in resource.data ? resource.data.total : undefined
  const truncated = resource.data && 'counts_truncated' in resource.data ? resource.data.counts_truncated : false
  const hasFilters = !!(canSearch && q || status || department || family)
  const dossierKey = companyKey && companyKey !== 'directory' ? companyKey : undefined
  const labels = { to_contact: t('À contacter', 'To contact'), contacted: t('Contactées', 'Contacted'), replied: t('Ont répondu', 'Replied') }
  return <main className={styles.workspace}>
    <header className={styles.heading}><div><h1>{t('Entreprises', 'Companies')}</h1><p>{t('Vos entreprises, vos interlocuteurs, votre prochaine action.', 'Your companies, your contacts, your next action.')}</p></div></header>
    <TargetBar independent={directoryMode} />
    <section className={styles.panel}>
      <div className={styles.tabs} role="tablist" aria-label={t('Vue entreprises', 'Company view')}>
        <button role="tab" className={styles.tab} aria-selected={!directoryMode} onClick={() => switchView(false)}>{t('Ma prospection', 'My prospects')}</button>
        <button role="tab" className={styles.tab} aria-selected={directoryMode} onClick={() => switchView(true)}>{t('Annuaire', 'Directory')}</button>
      </div>
      <div className={styles.toolbar}>
        <label className={styles.search}><Search aria-hidden="true" /><input type="search" maxLength={120} disabled={!canSearch} aria-describedby={!canSearch ? 'company-search-access' : undefined} aria-label={t('Rechercher dans la vue active', 'Search current view')} placeholder={t('Entreprise, activité, localisation…', 'Company, activity, location…')} value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} /></label>
        {!canSearch && <span id="company-search-access" className={styles.muted}>{t('La recherche dans votre prospection est disponible dès Essentiel. La recherche dans l’annuaire reste accessible.', 'Search within your prospects is available with Essential. Directory search remains available.')}</span>}
        <button className={styles.button} aria-expanded={filtersOpen} onClick={() => setFiltersOpen((open) => !open)}><SlidersHorizontal aria-hidden="true" />{t('Filtres', 'Filters')}</button>
        <select aria-label={t('Trier les résultats', 'Sort results')} value={sort} onChange={(event) => updateParams({ sort: event.target.value })}>
          {directoryMode ? <><option value="name">{t('Nom de l’entreprise', 'Company name')}</option><option value="city">{t('Ville du siège', 'Office city')}</option></>
            : <><option value="recent">{t('Publication récente', 'Recent publication')}</option><option value="amount">{t('Montant du dernier avis', 'Latest award value')}</option></>}
        </select>
      </div>
      {filtersOpen && <div className={styles.toolbar}>
        {directoryMode ? <>
          <label className={styles.field}><span>{t('Famille d’activité', 'Activity family')}</span><select aria-label={t('Famille d’activité', 'Activity family')} disabled={!directoryOptions.data} value={family} onChange={(event) => updateParams({ family: event.target.value })}><option value="">{t('Toutes les familles', 'All families')}</option>{directoryOptions.data?.families.map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}</select></label>
          <label className={styles.field}><span>{t('Département du siège', 'Office department')}</span><select aria-label={t('Département du siège', 'Office department')} disabled={!directoryOptions.data} value={department} onChange={(event) => updateParams({ department: event.target.value })}><option value="">{t('Tous les départements', 'All departments')}</option>{directoryOptions.data?.departments.map((option) => <option key={option.code} value={option.code}>{option.label}</option>)}</select></label>
          {directoryOptions.error && <button className={styles.textButton} onClick={directoryOptions.reload}>{t('Réessayer le chargement des filtres', 'Retry loading filters')}</button>}
        </> : <label className={styles.field}><span>{t('Suivi commercial', 'Commercial follow-up')}</span><select aria-label={t('Suivi commercial', 'Commercial follow-up')} value={status ?? ''} onChange={(event) => updateParams({ contact_status: event.target.value })}>
          <option value="">{t('Toutes', 'All')}</option>{(['to_contact', 'contacted', 'replied'] as const).map((value) => <option value={value} key={value}>{labels[value]}{counts && value in counts ? ` · ${number((counts as Record<CompanyContactStatus, number>)[value])}${truncated ? '+' : ''}` : ''}</option>)}
        </select></label>}
        {hasFilters && <button className={styles.textButton} onClick={() => updateParams({ q: null, contact_status: null, department: null, family: null })}>{t('Effacer les filtres', 'Clear filters')}</button>}
      </div>}
      <div className={styles.resultMeta} aria-live="polite"><strong>{typeof total === 'number' ? `${number(total)}${truncated ? '+' : ''} ${locale === 'fr' ? `entreprise${total === 1 ? '' : 's'}` : `compan${total === 1 ? 'y' : 'ies'}`}` : t('Entreprises', 'Companies')}</strong><span>{directoryMode ? t('Annuaire · fiches entreprise', 'Directory · company profiles') : t('Issues de vos signaux et de vos ajouts', 'From your signals and additions')}</span></div>
      {resource.loading ? <p className={styles.loading} role="status">{t('Chargement des entreprises…', 'Loading companies…')}</p>
        : resource.error ? <div className={styles.empty}><p className={styles.error} role="alert">{t('La liste n’a pas pu être chargée.', 'The list could not be loaded.')}</p><button className={styles.button} onClick={resource.reload}>{t('Réessayer', 'Retry')}</button></div>
          : directoryMode ? <DirectoryResults items={rows as DirectorySearchPage['items']} search={location.search} returnTo={listPath} />
            : rows.length ? <CompanyTable items={rows} search={location.search} returnTo={listPath} /> : <div className={styles.empty}><h2>{hasFilters ? t('Aucun résultat avec ces filtres.', 'No results with these filters.') : t('Votre prospection est prête à accueillir des entreprises.', 'Your prospects are ready for new companies.')}</h2><p>{t('Retrouvez une entreprise depuis vos signaux ou ajoutez-la depuis l’annuaire.', 'Find a company from your signals or add one from the directory.')}</p><button className={styles.button} onClick={() => hasFilters ? updateParams({ q: null, contact_status: null }) : switchView(true)}>{hasFilters ? t('Réinitialiser cette vue', 'Reset view') : t('Explorer l’annuaire', 'Explore directory')}</button></div>}
      {!resource.loading && !resource.error && <footer className={styles.footer}><span className={styles.muted}>{t('Ouvrez un dossier pour préparer votre prochaine action.', 'Open a dossier to prepare your next action.')}</span>{nextCursor && <button className={styles.button} disabled={pagination?.loading} onClick={() => void loadMore()}>{pagination?.loading ? t('Chargement…', 'Loading…') : t('Charger plus', 'Load more')}</button>}</footer>}
      {pagination?.error && <p className={styles.error} role="alert">{t('La page suivante n’a pas été chargée. Vous pouvez réessayer.', 'The next page could not be loaded. Please retry.')}</p>}
    </section>
    {(dossierKey || directorySiren) && <CompanyDossier companyKey={dossierKey} directorySiren={directorySiren} onClose={closeDossier} onUpgrade={(addressedKey) => setUpgradeIntent({ kind: 'company', companyKey: addressedKey })} />}
    {upgradeIntent && <UpgradeDialog intent={upgradeIntent} onClose={() => setUpgradeIntent(null)} />}
  </main>
}
