import { useCallback, useEffect, useRef, useState } from 'react'
import { AcquisitionStatus } from './AcquisitionStatus'
import {
  approveFounderProspect,
  correctFounderProspect,
  FounderApiError,
  loadFounderProspectionActions,
  rejectFounderProspect,
  sendFounderProspects,
} from './api'
import type {
  FounderDirectoryQualificationStatus,
  FounderDirectoryRow,
  FounderDirectoryStatus,
  FounderProspection,
  FounderProspectionActionTarget,
  FounderProspectionCorrectionChanges,
  FounderProspectionRejectionReason,
  FounderProspectionFilters,
} from './types'

const FAMILY_LABELS: Record<string, string> = {
  ready_mix_concrete: 'Béton prêt à l’emploi',
  reinforcement_steel: 'Armatures / acier',
  subcontracted_structural_work: 'Gros œuvre sous-traité',
  formwork: 'Coffrage',
  scaffolding: 'Échafaudage',
  plastering: 'Plâtrerie',
  flooring: 'Revêtements de sol',
  exterior_joinery: 'Menuiserie extérieure',
  plumbing: 'Plomberie',
  electrical: 'Électricité',
  hvac: 'Chauffage et ventilation',
  road_construction: 'Travaux routiers',
  asphalt: 'Enrobés et asphalte',
  road_markings: 'Signalisation routière',
  earthmoving: 'Terrassement',
  demolition: 'Démolition',
  waste_removal: 'Évacuation des déchets',
  waterproofing: 'Étanchéité',
  structural_steel: 'Charpente métallique',
  facade_cladding: 'Bardage et façade',
  timber_carpentry: 'Bois et charpente',
  roofing: 'Couverture et zinguerie',
  insulation: 'Isolation',
}

const DIRECTORY_STATUS_LABELS: Record<FounderDirectoryStatus, string> = {
  confirmed_domain: 'Domaine confirmé',
  without_website: 'Sans site',
  reverification_required: 'À revérifier',
}

type ProspectionPageProps = {
  data: FounderProspection
  filters: FounderProspectionFilters
  refreshing: boolean
  onFiltersChange: (filters: FounderProspectionFilters) => void
}

export function ProspectionPage({
  data,
  filters,
  refreshing,
  onFiltersChange,
}: ProspectionPageProps) {
  const [openMail, setOpenMail] = useState<FounderProspectionActionTarget | null>(null)
  const mailTriggerRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!openMail) return undefined
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenMail(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [openMail])

  useEffect(() => {
    if (!openMail) mailTriggerRef.current?.focus()
  }, [openMail])

  return (
    <>
      <ProspectionHero data={data} />
      <QueueSection
        data={data}
        onOpenMail={(item, trigger) => {
          mailTriggerRef.current = trigger
          setOpenMail(item)
        }}
      />
      <DirectorySection
        data={data}
        filters={filters}
        refreshing={refreshing}
        onFiltersChange={onFiltersChange}
      />
      <TargetingSection data={data} />
      <ResultsSection data={data} />
      {openMail ? <MailDrawer item={openMail} onClose={() => setOpenMail(null)} /> : null}
    </>
  )
}

function ProspectionHero({ data }: { data: FounderProspection }) {
  return (
    <section className="control-section prospection-hero" aria-labelledby="prospection-title">
      <div>
        <p className="control-eyebrow">Acquisition assistée</p>
        <h1 id="prospection-title">Prospection</h1>
        <p>
          L’annuaire réel, le dernier cycle d’acquisition et la revue assistée réunis
          dans une vue opérationnelle.
        </p>
      </div>
      <AcquisitionStatus status={data.acquisition_status} compact />
    </section>
  )
}

function DirectorySection({
  data,
  filters,
  refreshing,
  onFiltersChange,
}: ProspectionPageProps) {
  const [searchDraft, setSearchDraft] = useState(filters.q)
  const { directory } = data
  const { pagination } = directory
  const firstRow = pagination.total_items === 0 ? 0 : (pagination.page - 1) * pagination.page_size + 1
  const lastRow = Math.min(pagination.page * pagination.page_size, pagination.total_items)

  useEffect(() => setSearchDraft(filters.q), [filters.q])

  const changeFilter = (change: Partial<FounderProspectionFilters>) => {
    onFiltersChange({ ...filters, ...change, page: change.page ?? 1 })
  }

  return (
    <section id="directory" className="control-section prospection-section" aria-labelledby="directory-title">
      <ProspectionSectionHeading
        eyebrow="Base fournisseurs"
        title="Annuaire"
        titleId="directory-title"
        description="Entreprises actives de l’annuaire fournisseurs. Les compteurs restent globaux pendant le filtrage."
        meta={`${formatCount(pagination.total_items)} résultats`}
      />

      <div className="prospection-kpi-grid" aria-label="Compteurs de l’annuaire">
        <ProspectionKpi label="Entreprises" value={directory.summary.company_count} />
        <ProspectionKpi label="Domaines confirmés" value={directory.summary.confirmed_domain_count} tone="positive" />
        <ProspectionKpi label="E-mails vérifiés" value={directory.summary.verified_email_count} tone="positive" />
        <ProspectionKpi label="À revérifier" value={directory.summary.reverification_required_count} tone="warning" />
      </div>

      <div className="prospection-facets">
        <FacetList
          label="Par famille"
          values={directory.family_counts.map((facet) => ({ ...facet, label: familyLabel(facet.key) }))}
        />
        <FacetList
          label="Par département"
          values={directory.department_counts}
        />
      </div>

      <form
        className="prospection-filters"
        role="search"
        onSubmit={(event) => {
          event.preventDefault()
          changeFilter({ q: searchDraft.trim() })
        }}
      >
        <label className="prospection-search">
          <span>Nom de l’entreprise</span>
          <span className="prospection-search-control">
            <input
              type="search"
              value={searchDraft}
              placeholder="Rechercher un fournisseur"
              onChange={(event) => setSearchDraft(event.target.value)}
            />
            <button type="submit" disabled={refreshing}>Rechercher</button>
          </span>
        </label>
        <FilterSelect
          label="Famille"
          value={filters.family}
          disabled={refreshing}
          onChange={(value) => changeFilter({ family: value })}
          options={directory.family_counts.map((facet) => ({
            value: facet.key,
            label: `${familyLabel(facet.key)} (${formatCount(facet.count)})`,
          }))}
        />
        <FilterSelect
          label="Département"
          value={filters.department}
          disabled={refreshing}
          onChange={(value) => changeFilter({ department: value })}
          options={directory.department_counts.map((facet) => ({
            value: facet.key,
            label: `${facet.label} (${formatCount(facet.count)})`,
          }))}
        />
        <FilterSelect
          label="Statut"
          value={filters.status}
          disabled={refreshing}
          onChange={(value) => changeFilter({ status: value as FounderDirectoryStatus | '' })}
          options={Object.entries(DIRECTORY_STATUS_LABELS).map(([value, label]) => ({ value, label }))}
        />
      </form>

      <article className={`control-panel prospection-table-panel ${refreshing ? 'prospection-refreshing' : ''}`}>
        {directory.rows.length === 0 ? (
          <div className="prospection-compact-empty">
            <strong>Aucune entreprise ne correspond à ces filtres.</strong>
            <span>Modifie les critères pour retrouver les fiches actives de l’annuaire.</span>
          </div>
        ) : (
          <div className="control-table-wrap prospection-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Entreprise</th>
                  <th>Métier</th>
                  <th>Localisation</th>
                  <th className="prospection-number">Effectif</th>
                  <th>Domaine</th>
                  <th>E-mail</th>
                  <th>État</th>
                </tr>
              </thead>
              <tbody>
                {directory.rows.map((row) => <DirectoryTableRow key={row.siren} row={row} />)}
              </tbody>
            </table>
          </div>
        )}
        <footer className="prospection-pagination">
          <span>{firstRow}–{lastRow} sur {formatCount(pagination.total_items)}</span>
          <div>
            <button
              type="button"
              disabled={refreshing || pagination.page <= 1}
              onClick={() => changeFilter({ page: pagination.page - 1 })}
            >
              Précédent
            </button>
            <span>Page {pagination.page} / {pagination.total_pages}</span>
            <button
              type="button"
              disabled={refreshing || pagination.page >= pagination.total_pages}
              onClick={() => changeFilter({ page: pagination.page + 1 })}
            >
              Suivant
            </button>
          </div>
        </footer>
      </article>
    </section>
  )
}

function DirectoryTableRow({ row }: { row: FounderDirectoryRow }) {
  const hasConfirmedDomain = row.qualification_status === 'confirmed_domain'
    && row.confirmed_domain
    && row.domain !== null
  return (
    <tr>
      <td>
        <strong className="prospection-primary-cell">{row.legal_name}</strong>
        <small>SIREN {row.siren}</small>
      </td>
      <td>
        <span className="prospection-family-list">
          {row.family_keys.map((family) => <span key={family}>{familyLabel(family)}</span>)}
        </span>
      </td>
      <td>
        <span>{row.city ?? '—'}</span>
        {row.department ? <small>Département {departmentLabel(row.department, row.department_name)}</small> : null}
      </td>
      <td className="prospection-number">{row.employees === null ? '—' : formatCount(row.employees)}</td>
      <td>
        {hasConfirmedDomain ? (
          <a href={confirmedWebsiteUrl(row)} target="_blank" rel="noreferrer">{row.domain}</a>
        ) : (
          <DirectoryStatus status="to_qualify" />
        )}
      </td>
      <td>
        {row.professional_email ? (
          <>
            <a href={`mailto:${row.professional_email}`}>{row.professional_email}</a>
            <EmailMetadata source={row.email_source} verificationStatus={row.email_verification_status} />
          </>
        ) : (
          <span className="prospection-missing">—</span>
        )}
      </td>
      <td>
        <DirectoryStatus status={row.qualification_status} />
        <small>Maj. {formatDate(row.updated_at)}</small>
      </td>
    </tr>
  )
}

function QueueSection({
  data,
  onOpenMail,
}: {
  data: FounderProspection
  onOpenMail: (item: FounderProspectionActionTarget, trigger: HTMLButtonElement) => void
}) {
  const [items, setItems] = useState<FounderProspectionActionTarget[]>([])
  const [loaded, setLoaded] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [queuePages, setQueuePages] = useState({
    pending_review: { next: null as number | null, remaining: 0 },
    approved: { next: null as number | null, remaining: 0 },
  })
  const [busyTargetIds, setBusyTargetIds] = useState<Set<string>>(new Set())
  const [killSwitchActive, setKillSwitchActive] = useState(false)
  const [correctingTarget, setCorrectingTarget] = useState<FounderProspectionActionTarget | null>(null)
  const [rejectingTarget, setRejectingTarget] = useState<FounderProspectionActionTarget | null>(null)
  const [sendConfirmationOpen, setSendConfirmationOpen] = useState(false)
  const [sendState, setSendState] = useState<'idle' | 'sending'>('idle')
  const [sendingCount, setSendingCount] = useState(0)
  const [sendNotice, setSendNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const sendRequestRef = useRef<{ fingerprint: string; requestId: string } | null>(null)

  const refreshQueue = useCallback(async (signal?: AbortSignal) => {
    const activeSignal = signal ?? new AbortController().signal
    const [pending, approved] = await Promise.all([
      loadFounderProspectionActions('pending_review', activeSignal),
      loadFounderProspectionActions('approved', activeSignal),
    ])
    if (activeSignal.aborted) return
    const merged = [...pending.items, ...approved.items]
    setItems(merged.filter((item, index) => (
      merged.findIndex((candidate) => candidate.target_id === item.target_id) === index
    )))
    setKillSwitchActive(pending.kill_switch_active || approved.kill_switch_active)
    setQueuePages({
      pending_review: {
        next: pending.pagination.total_pages > 1 ? 2 : null,
        remaining: Math.max(0, pending.pagination.total_items - pending.items.length),
      },
      approved: {
        next: approved.pagination.total_pages > 1 ? 2 : null,
        remaining: Math.max(0, approved.pagination.total_items - approved.items.length),
      },
    })
    setLoaded(true)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setLoaded(false)
    setActionError(null)
    void refreshQueue(controller.signal).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setLoaded(true)
        setActionError(founderActionErrorMessage(error, 'Impossible de charger la file de prospection.'))
      }
    })
    return () => controller.abort()
  }, [data.generated_at, refreshQueue])

  const loadMore = async () => {
    if (loadingMore) return
    const requests: Array<Promise<{
      status: 'pending_review' | 'approved'
      response: Awaited<ReturnType<typeof loadFounderProspectionActions>>
    }>> = []
    for (const status of ['pending_review', 'approved'] as const) {
      const page = queuePages[status].next
      if (page !== null) {
        const controller = new AbortController()
        requests.push(loadFounderProspectionActions(status, controller.signal, page)
          .then((response) => ({ status, response })))
      }
    }
    if (requests.length === 0) return
    setLoadingMore(true)
    setActionError(null)
    try {
      const pages = await Promise.all(requests)
      setItems((current) => {
        const merged = [...current, ...pages.flatMap(({ response }) => response.items)]
        return merged.filter((item, index) => (
          merged.findIndex((candidate) => candidate.target_id === item.target_id) === index
        ))
      })
      setQueuePages((current) => {
        const next = { ...current }
        for (const { status, response } of pages) {
          next[status] = {
            next: response.pagination.page < response.pagination.total_pages
              ? response.pagination.page + 1
              : null,
            remaining: Math.max(0, current[status].remaining - response.items.length),
          }
        }
        return next
      })
    } catch (error) {
      setActionError(founderActionErrorMessage(error, 'Impossible de charger la suite de la file.'))
    } finally {
      setLoadingMore(false)
    }
  }

  const approve = async (target: FounderProspectionActionTarget) => {
    setActionError(null)
    setBusyTargetIds((current) => new Set(current).add(target.target_id))
    setItems((current) => current.map((item) => item.target_id === target.target_id
      ? { ...item, status: 'approved', version: item.version + 1 }
      : item))
    try {
      const response = await approveFounderProspect(target.target_id, target.version)
      setItems((current) => current.map((item) => item.target_id === target.target_id
        ? response.target
        : item))
    } catch (error) {
      setItems((current) => current.map((item) => item.target_id === target.target_id
        ? target
        : item))
      setActionError(founderActionErrorMessage(error, 'La validation a échoué.'))
    } finally {
      setBusyTargetIds((current) => {
        const next = new Set(current)
        next.delete(target.target_id)
        return next
      })
    }
  }
  const correct = async (
    target: FounderProspectionActionTarget,
    changes: FounderProspectionCorrectionChanges,
  ): Promise<boolean> => {
    setActionError(null)
    setBusyTargetIds((current) => new Set(current).add(target.target_id))
    const optimistic: FounderProspectionActionTarget = {
      ...target,
      version: target.version + 1,
      company: {
        ...target.company,
        name: changes.company_name ?? target.company.name,
      },
      director: changes.director_name
        ? {
            name: changes.director_name,
            title: target.director?.title ?? 'dirigeant',
            source: 'manual',
          }
        : target.director,
      email: changes.email_address
        ? { ...target.email, address: changes.email_address, source: 'manual' }
        : target.email,
    }
    setItems((current) => current.map((item) => item.target_id === target.target_id
      ? optimistic
      : item))
    try {
      const response = await correctFounderProspect(target.target_id, target.version, changes)
      setItems((current) => current.map((item) => item.target_id === target.target_id
        ? response.target
        : item))
      return true
    } catch (error) {
      setItems((current) => current.map((item) => item.target_id === target.target_id
        ? target
        : item))
      setActionError(founderActionErrorMessage(error, 'La correction a échoué.'))
      return false
    } finally {
      setBusyTargetIds((current) => {
        const next = new Set(current)
        next.delete(target.target_id)
        return next
      })
    }
  }
  const reject = async (
    target: FounderProspectionActionTarget,
    reason: FounderProspectionRejectionReason,
    comment?: string,
  ): Promise<boolean> => {
    setActionError(null)
    setBusyTargetIds((current) => new Set(current).add(target.target_id))
    setItems((current) => current.map((item) => item.target_id === target.target_id
      ? { ...item, status: 'rejected', version: item.version + 1 }
      : item))
    try {
      await rejectFounderProspect(target.target_id, target.version, reason, comment)
      return true
    } catch (error) {
      setItems((current) => current.map((item) => item.target_id === target.target_id
        ? target
        : item))
      setActionError(founderActionErrorMessage(error, 'L’écartement a échoué.'))
      return false
    } finally {
      setBusyTargetIds((current) => {
        const next = new Set(current)
        next.delete(target.target_id)
        return next
      })
    }
  }
  const approvedCount = items.filter((item) => item.status === 'approved').length
  const sendBatchCount = Math.min(approvedCount, 25)
  const remainingQueueCount = queuePages.pending_review.remaining + queuePages.approved.remaining
  const visibleItems = items.filter((item) => item.status === 'pending_review' || item.status === 'approved')
  const sendApproved = async () => {
    const approved = items.filter((item) => item.status === 'approved').slice(0, 25)
    if (approved.length === 0 || sendState === 'sending') return
    const fingerprint = approved
      .map((item) => `${item.target_id}:${item.version}`)
      .sort()
      .join('|')
    const requestId = sendRequestRef.current?.fingerprint === fingerprint
      ? sendRequestRef.current.requestId
      : crypto.randomUUID()
    sendRequestRef.current = { fingerprint, requestId }
    setSendConfirmationOpen(false)
    setActionError(null)
    setSendNotice(null)
    setSendingCount(approved.length)
    setSendState('sending')
    const batchIds = new Set(approved.map((item) => item.target_id))
    setItems((current) => current.map((item) => batchIds.has(item.target_id)
      ? { ...item, status: 'sent', version: item.version + 1 }
      : item))
    try {
      const response = await sendFounderProspects(
        requestId,
        approved.map((item) => ({ target_id: item.target_id, expected_version: item.version })),
      )
      const failedIds = new Set(response.results
        .filter((result) => result.status === 'failed')
        .map((result) => result.target_id))
      sendRequestRef.current = null
      if (failedIds.size > 0) {
        setSendNotice(`${failedIds.size} cible${failedIds.size === 1 ? '' : 's'} non envoyée${failedIds.size === 1 ? '' : 's'}.`)
      } else {
        setSendNotice(`${approved.length} cible${approved.length === 1 ? '' : 's'} envoyée${approved.length === 1 ? '' : 's'}.`)
      }
      try {
        await refreshQueue()
      } catch (error) {
        setActionError(founderActionErrorMessage(
          error,
          'L’envoi est enregistré, mais la file n’a pas pu être actualisée. Recharge la page.',
        ))
      }
    } catch (error) {
      const message = founderActionErrorMessage(error, 'L’envoi a échoué.')
      if (error instanceof FounderApiError && error.code) {
        sendRequestRef.current = null
        try {
          await refreshQueue()
          setActionError(message)
        } catch {
          setActionError(`${message} La file n’a pas pu être actualisée ; recharge la page.`)
        }
      } else {
        setItems((current) => current.map((item) => (
          batchIds.has(item.target_id)
            ? approved.find((candidate) => candidate.target_id === item.target_id) ?? item
            : item
        )))
        setActionError(message)
      }
    } finally {
      setSendState('idle')
    }
  }
  return (
    <section id="queue" className="control-section prospection-section prospection-compact-section" aria-labelledby="queue-title">
      <ProspectionSectionHeading
        eyebrow="Revue assistée"
        title="File du jour"
        titleId="queue-title"
        description="Cibles préparées pour revue, correction et envoi manuel."
        meta={cycleDateLabel(data.queue.last_cycle_at)}
      />
      <article className="control-panel prospection-queue-panel">
        {actionError ? <p className="prospection-action-error" role="alert">{actionError}</p> : null}
        {!loaded ? (
          <div className="prospection-compact-empty">
            <strong>Chargement de la file…</strong>
          </div>
        ) : visibleItems.length === 0 ? (
          <div className="prospection-compact-empty">
            <strong>Aucune cible en attente de revue.</strong>
            <span>La Session A n’a encore préparé aucune cible.</span>
          </div>
        ) : (
          <div className="control-table-wrap prospection-table-wrap prospection-queue-table">
            <table>
              <thead>
                <tr>
                  <th>Entreprise</th>
                  <th>Métier</th>
                  <th>Dirigeant</th>
                  <th>E-mail</th>
                  <th>Signal d’appât</th>
                  <th>Mail</th>
                  <th>Décision</th>
                </tr>
              </thead>
              <tbody>
                {visibleItems.map((item) => (
                  <tr
                    key={item.target_id}
                    className={item.status === 'approved' ? 'prospection-row-approved' : undefined}
                  >
                    <td>
                      <strong className="prospection-primary-cell">{item.company.name}</strong>
                      <small>{item.company.city} · {formatCount(item.company.employees)} salariés</small>
                    </td>
                    <td>{item.company.family}</td>
                    <td>
                      <span>{item.director?.name ?? '—'}</span>
                      {item.director?.title ? <small>{item.director.title}</small> : null}
                    </td>
                    <td>
                      <span>{item.email.address}</span>
                      <EmailMetadata source={item.email.source} verificationStatus={item.email.verification_status} />
                    </td>
                    <td>
                      <strong className="prospection-primary-cell">{item.signal.holder}</strong>
                      <span>{item.signal.subject}</span>
                      <small>{formatOptionalMoney(item.signal.amount_minor_units, item.signal.currency)}</small>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="prospection-mail-button"
                        aria-label={`Voir le mail de ${item.company.name}`}
                        onClick={(event) => onOpenMail(item, event.currentTarget)}
                      >
                        Voir
                      </button>
                    </td>
                    <td>
                      <div className="prospection-row-actions">
                        <button
                          type="button"
                          disabled={item.status === 'approved' || busyTargetIds.has(item.target_id)}
                          onClick={() => void approve(item)}
                        >
                          {item.status === 'approved' ? 'Validée' : 'Valider'}
                        </button>
                        <button
                          type="button"
                          disabled={busyTargetIds.has(item.target_id)}
                          onClick={() => setCorrectingTarget(item)}
                        >
                          Corriger
                        </button>
                        <button
                          type="button"
                          disabled={busyTargetIds.has(item.target_id)}
                          onClick={() => setRejectingTarget(item)}
                        >
                          Écarter
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <footer className="prospection-queue-footer">
          <span>{approvedCount === 1 ? '1 cible validée' : `${formatCount(approvedCount)} cibles validées`}</span>
          <div className="prospection-queue-footer-actions">
            {remainingQueueCount > 0 ? (
              <button type="button" disabled={loadingMore} onClick={() => void loadMore()}>
                {loadingMore
                  ? 'Chargement de la suite…'
                  : `Charger la suite · ${formatCount(remainingQueueCount)} restante${remainingQueueCount === 1 ? '' : 's'}`}
              </button>
            ) : null}
            <button
              type="button"
              className="prospection-action-primary"
              disabled={sendBatchCount === 0 || sendState === 'sending' || killSwitchActive}
              aria-label={sendBatchLabel(approvedCount)}
              onClick={() => setSendConfirmationOpen(true)}
            >
              {sendBatchLabel(approvedCount)}
            </button>
          </div>
        </footer>
        {killSwitchActive ? (
          <p className="prospection-action-warning" role="status">
            Envois suspendus par le coupe-circuit.
          </p>
        ) : null}
        {sendState === 'sending' ? (
          <p className="prospection-action-notice" role="status">
            {sendingCount === 1 ? 'Envoi de la cible…' : `Envoi de ${sendingCount} cibles…`}
          </p>
        ) : null}
        {sendNotice ? <p className="prospection-action-notice" role="status">{sendNotice}</p> : null}
      </article>
      {correctingTarget ? (
        <CorrectionDrawer
          item={correctingTarget}
          busy={busyTargetIds.has(correctingTarget.target_id)}
          onClose={() => setCorrectingTarget(null)}
          onSubmit={(changes) => correct(correctingTarget, changes)}
        />
      ) : null}
      {rejectingTarget ? (
        <RejectionDrawer
          item={rejectingTarget}
          busy={busyTargetIds.has(rejectingTarget.target_id)}
          onClose={() => setRejectingTarget(null)}
          onSubmit={(reason, comment) => reject(rejectingTarget, reason, comment)}
        />
      ) : null}
      {sendConfirmationOpen ? (
        <SendConfirmationDrawer
          count={sendBatchCount}
          onClose={() => setSendConfirmationOpen(false)}
          onConfirm={() => void sendApproved()}
        />
      ) : null}
    </section>
  )
}

function sendBatchLabel(approvedCount: number): string {
  if (approvedCount === 1) return 'Envoyer la cible validée'
  if (approvedCount > 25) return 'Envoyer les 25 premières cibles validées'
  return `Envoyer les ${approvedCount} cibles validées`
}

function founderActionErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof FounderApiError) {
    return error.code
      ? `${error.message} (${error.code})`
      : `${error.message} (HTTP ${error.status})`
  }
  return fallback
}

function SendConfirmationDrawer({
  count,
  onClose,
  onConfirm,
}: {
  count: number
  onClose: () => void
  onConfirm: () => void
}) {
  return (
    <div className="prospection-drawer-backdrop">
      <aside className="prospection-drawer" role="dialog" aria-label={`Confirmer l’envoi de ${count} cibles`}>
        <header>
          <div><small>Dernière confirmation</small><h2>Envoyer {count} cibles</h2></div>
          <button type="button" aria-label="Fermer" onClick={onClose}>×</button>
        </header>
        <div className="prospection-action-confirmation">
          <p>Les cibles validées seront transmises à Instantly. Cette action démarre réellement leur envoi.</p>
          <footer>
            <button type="button" onClick={onClose}>Annuler</button>
            <button type="button" className="prospection-action-primary" onClick={onConfirm}>
              Envoyer maintenant
            </button>
          </footer>
        </div>
      </aside>
    </div>
  )
}

function TargetingSection({ data }: { data: FounderProspection }) {
  const cycle = data.targeting
  return (
    <section id="targeting" className="control-section prospection-section prospection-compact-section" aria-labelledby="targeting-title">
      <ProspectionSectionHeading
        eyebrow="Dernier passage"
        title="Sélection"
        titleId="targeting-title"
        description="Signal, volume et écarts lus dans le journal de sélection du dernier cycle d’acquisition."
        meta={cycleDateLabel(cycle?.updated_at ?? null)}
      />
      {!cycle ? (
        <CompactEmpty title="Aucun cycle enregistré." body="Le runtime n’a produit aucun journal de sélection." />
      ) : !cycle.recent ? (
        <CompactEmpty title="Aucun cycle récent." body={`Dernier cycle le ${formatDateTime(cycle.updated_at)} · ${cycleStatusLabel(cycle.status)}.`} />
      ) : (
        <article className="control-panel prospection-targeting-grid">
          <div className="prospection-signal">
            <small>Signal choisi</small>
            <strong>{cycle.signal.title ?? 'Signal non résolu'}</strong>
            <span>{formatOptionalMoney(cycle.signal.amount_minor_units, cycle.signal.currency)}</span>
          </div>
          <CompactMetric label="Comptes SIRENE" value={cycle.sirene_account_count} />
          <CompactMetric label="Domaines confirmés" value={cycle.confirmed_domain_count} />
          <div className="prospection-inline-list">
            <small>Familles</small>
            <span>{cycle.family_keys.length > 0 ? cycle.family_keys.map(familyLabel).join(' · ') : '—'}</span>
          </div>
          <div className="prospection-inline-list">
            <small>E-mails par niveau</small>
            <span>{cycle.email_counts_by_level.map((level) => `N${level.level} ${formatCount(level.count)}`).join(' · ') || '—'}</span>
          </div>
          <div className="prospection-inline-list">
            <small>Écarts par motif</small>
            <span>{cycle.deviation_counts.map((deviation) => `${deviationLabel(deviation.reason_code)} ${formatCount(deviation.count)}`).join(' · ') || 'Aucun écart'}</span>
          </div>
        </article>
      )}
    </section>
  )
}

function ResultsSection({ data }: { data: FounderProspection }) {
  const { results } = data
  return (
    <section id="results" className="control-section prospection-section prospection-compact-section" aria-labelledby="results-title">
      <ProspectionSectionHeading
        eyebrow="Boucle commerciale"
        title="Résultats"
        titleId="results-title"
        description="Progression observée depuis les envois jusqu’au revenu récurrent."
        meta={`Actualisé ${formatDateTime(data.generated_at)}`}
      />
      <div className="prospection-results-grid">
        <CompactMetric label="Envoyés" value={results.sent_count} />
        <CompactMetric label="Ouvertures" value={results.opened_count} />
        <CompactMetric label="Clics /a/{token}" value={results.attribution_click_count} />
        <CompactMetric label="Atterrissages" value={results.landing_count} />
        <CompactMetric label="Profils confirmés" value={results.confirmed_profile_count} />
        <CompactMetric label="Comptes payants" value={results.paid_account_count} />
        <CompactMetric
          label="MRR"
          value={results.mrr_by_currency.length > 0
            ? results.mrr_by_currency.map((money) => formatMoney(money.minor_units, money.currency)).join(' · ')
            : '0'}
        />
      </div>
      {results.no_sends_yet ? <p className="prospection-no-send">Aucun envoi à ce jour.</p> : null}
    </section>
  )
}

function MailDrawer({ item, onClose }: { item: FounderProspectionActionTarget; onClose: () => void }) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    closeButtonRef.current?.focus()
  }, [])

  return (
    <div className="prospection-drawer-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <aside
        className="prospection-drawer"
        role="dialog"
        aria-label={`Mail préparé pour ${item.company.name}`}
      >
        <header>
          <div>
            <small>Mail préparé</small>
            <h2 id="prospection-mail-title">{item.company.name}</h2>
          </div>
          <button ref={closeButtonRef} type="button" aria-label="Fermer" onClick={onClose}>×</button>
        </header>
        <dl>
          <div><dt>À</dt><dd>{item.email.address}</dd></div>
          <div><dt>Objet</dt><dd>{item.mail.subject}</dd></div>
        </dl>
        <iframe
          className="prospection-mail-preview"
          title="Aperçu HTML du mail"
          sandbox=""
          srcDoc={item.mail.html}
        />
        <footer>L’envoi s’effectue depuis le lot de cibles validées.</footer>
      </aside>
    </div>
  )
}

function CorrectionDrawer({
  item,
  busy,
  onClose,
  onSubmit,
}: {
  item: FounderProspectionActionTarget
  busy: boolean
  onClose: () => void
  onSubmit: (changes: FounderProspectionCorrectionChanges) => Promise<boolean>
}) {
  const [companyName, setCompanyName] = useState(item.company.name)
  const [directorName, setDirectorName] = useState(item.director?.name ?? '')
  const [emailAddress, setEmailAddress] = useState(item.email.address)
  const changes: FounderProspectionCorrectionChanges = {}
  if (companyName.trim() && companyName.trim() !== item.company.name) {
    changes.company_name = companyName.trim()
  }
  if (directorName.trim() && directorName.trim() !== (item.director?.name ?? '')) {
    changes.director_name = directorName.trim()
  }
  if (emailAddress.trim() && emailAddress.trim() !== item.email.address) {
    changes.email_address = emailAddress.trim()
  }
  const changed = Object.keys(changes).length > 0

  return (
    <div className="prospection-drawer-backdrop">
      <aside className="prospection-drawer" role="dialog" aria-label={`Corriger ${item.company.name}`}>
        <header>
          <div><small>Correction auditée</small><h2>{item.company.name}</h2></div>
          <button type="button" aria-label="Fermer" disabled={busy} onClick={onClose}>×</button>
        </header>
        <form
          className="prospection-action-form"
          onSubmit={(event) => {
            event.preventDefault()
            void onSubmit(changes).then((accepted) => {
              if (accepted) onClose()
            })
          }}
        >
          <label>
            <span>Nom de l’entreprise</span>
            <input required value={companyName} onChange={(event) => setCompanyName(event.target.value)} />
          </label>
          <label>
            <span>Dirigeant</span>
            <input value={directorName} onChange={(event) => setDirectorName(event.target.value)} />
          </label>
          <label>
            <span>Adresse e-mail</span>
            <input required type="email" value={emailAddress} onChange={(event) => setEmailAddress(event.target.value)} />
          </label>
          <footer>
            <button type="button" disabled={busy} onClick={onClose}>Annuler</button>
            <button type="submit" className="prospection-action-primary" disabled={busy || !changed}>
              {busy ? 'Enregistrement…' : 'Enregistrer les corrections'}
            </button>
          </footer>
        </form>
      </aside>
    </div>
  )
}

const REJECTION_REASONS: Array<{ value: FounderProspectionRejectionReason; label: string }> = [
  { value: 'wrong_company', label: 'Mauvaise entreprise' },
  { value: 'wrong_address', label: 'Mauvaise adresse' },
  { value: 'off_topic', label: 'Hors sujet' },
  { value: 'other', label: 'Autre' },
]

function RejectionDrawer({
  item,
  busy,
  onClose,
  onSubmit,
}: {
  item: FounderProspectionActionTarget
  busy: boolean
  onClose: () => void
  onSubmit: (reason: FounderProspectionRejectionReason, comment?: string) => Promise<boolean>
}) {
  const [reason, setReason] = useState<FounderProspectionRejectionReason | ''>('')
  const [comment, setComment] = useState('')
  const valid = reason !== '' && (reason !== 'other' || comment.trim().length > 0)
  return (
    <div className="prospection-drawer-backdrop">
      <aside className="prospection-drawer" role="dialog" aria-label={`Écarter ${item.company.name}`}>
        <header>
          <div><small>Décision auditée</small><h2>{item.company.name}</h2></div>
          <button type="button" aria-label="Fermer" disabled={busy} onClick={onClose}>×</button>
        </header>
        <form
          className="prospection-action-form"
          onSubmit={(event) => {
            event.preventDefault()
            if (!valid || !reason) return
            void onSubmit(reason, comment.trim() || undefined).then((accepted) => {
              if (accepted) onClose()
            })
          }}
        >
          <label>
            <span>Motif</span>
            <select value={reason} onChange={(event) => setReason(event.target.value as FounderProspectionRejectionReason | '')}>
              <option value="">Choisir un motif</option>
              {REJECTION_REASONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Commentaire{reason === 'other' ? ' (obligatoire)' : ' (facultatif)'}</span>
            <textarea value={comment} maxLength={2000} onChange={(event) => setComment(event.target.value)} />
          </label>
          <footer>
            <button type="button" disabled={busy} onClick={onClose}>Annuler</button>
            <button type="submit" className="prospection-action-danger" disabled={busy || !valid}>
              {busy ? 'Écartement…' : 'Confirmer l’écartement'}
            </button>
          </footer>
        </form>
      </aside>
    </div>
  )
}

function FilterSelect({
  label,
  value,
  disabled,
  options,
  onChange,
}: {
  label: string
  value: string
  disabled: boolean
  options: Array<{ value: string; label: string }>
  onChange: (value: string) => void
}) {
  return (
    <label>
      <span>{label}</span>
      <select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        <option value="">Tous</option>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  )
}

function DirectoryStatus({ status }: { status: FounderDirectoryQualificationStatus }) {
  const className = status === 'reverification_required'
    ? 'prospection-pill prospection-pill-warning'
    : status === 'confirmed_domain'
      ? 'prospection-pill prospection-pill-positive'
      : 'prospection-pill'
  return <span className={className}>{qualificationStatusLabel(status)}</span>
}

function EmailMetadata({
  source,
  verificationStatus,
}: {
  source: string | null
  verificationStatus: string | null
}) {
  return (
    <small>
      <span>{sourceLabel(source)}</span>
      {' · '}
      <span>{emailVerificationLabel(verificationStatus)}</span>
    </small>
  )
}

function FacetList({ label, values }: { label: string; values: Array<{ key: string; label: string; count: number }> }) {
  return (
    <div>
      <span>{label}</span>
      <ul>
        {values.map((value) => (
          <li key={value.key}><span>{value.label}</span><strong>{formatCount(value.count)}</strong></li>
        ))}
      </ul>
    </div>
  )
}

function ProspectionKpi({ label, value, tone = 'neutral' }: { label: string; value: number; tone?: 'neutral' | 'positive' | 'warning' }) {
  return (
    <article className={`prospection-kpi prospection-kpi-${tone}`}>
      <span>{label}</span>
      <strong>{formatCount(value)}</strong>
    </article>
  )
}

function CompactMetric({ label, value }: { label: string; value: number | string }) {
  return (
    <article className="prospection-compact-metric">
      <span>{label}</span>
      <strong>{typeof value === 'number' ? formatCount(value) : value}</strong>
    </article>
  )
}

function ProspectionSectionHeading({
  eyebrow,
  title,
  titleId,
  description,
  meta,
}: {
  eyebrow: string
  title: string
  titleId: string
  description: string
  meta: string
}) {
  return (
    <div className="prospection-section-heading">
      <div>
        <p className="control-eyebrow">{eyebrow}</p>
        <h2 id={titleId}>{title}</h2>
        <p>{description}</p>
      </div>
      <span>{meta}</span>
    </div>
  )
}

function CompactEmpty({ title, body }: { title: string; body: string }) {
  return (
    <div className="prospection-compact-empty control-panel">
      <strong>{title}</strong>
      <span>{body}</span>
    </div>
  )
}

function familyLabel(value: string): string {
  return FAMILY_LABELS[value] ?? 'Famille non répertoriée'
}

function sourceLabel(value: string | null): string {
  if (!value) return 'Source inconnue'
  const labels: Record<string, string> = { apollo: 'Apollo', site: 'Site', manual: 'Manuel' }
  return labels[value.toLowerCase()] ?? 'Source non répertoriée'
}

function emailVerificationLabel(value: string | null): string {
  if (!value) return 'Vérification inconnue'
  const labels: Record<string, string> = {
    mx_verified: 'MX vérifié',
    mx_accepted: 'MX vérifié',
    provider_verified: 'Vérifié par le fournisseur',
    deliverability_verified: 'Délivrabilité vérifiée',
    verified: 'Vérifié',
  }
  return labels[value.toLowerCase()] ?? 'Statut de vérification non répertorié'
}

function qualificationStatusLabel(status: FounderDirectoryQualificationStatus): string {
  const labels: Record<FounderDirectoryQualificationStatus, string> = {
    confirmed_domain: 'Domaine confirmé',
    reverification_required: 'À revérifier',
    without_website: 'Sans site',
    to_qualify: 'À qualifier',
  }
  return labels[status]
}

function departmentLabel(code: string, name: string | null): string {
  return name ? `${name} (${code})` : code
}

function confirmedWebsiteUrl(row: FounderDirectoryRow): string {
  if (row.website_url?.startsWith('https://') || row.website_url?.startsWith('http://')) {
    return row.website_url
  }
  return `https://${row.domain ?? ''}`
}

function cycleStatusLabel(value: string): string {
  const labels: Record<string, string> = {
    suppressed: 'Supprimé',
    succeeded: 'Réussi',
    failed: 'Échoué',
    running: 'En cours',
    abandoned: 'Abandonné',
    pending: 'En attente',
    waiting: 'En attente de traitement',
    blocked: 'Bloqué',
    cancelled: 'Annulé',
  }
  return labels[value.toLowerCase()] ?? 'État du cycle non répertorié'
}

function deviationLabel(value: string): string {
  const labels: Record<string, string> = {
    contact_identity_unresolved: 'Identité du contact non résolue',
    confirmed_domain_not_found: 'Aucun domaine confirmé',
    verified_email_not_found: 'Aucun e-mail vérifié',
    no_eligible_supplier: 'Aucun fournisseur éligible',
  }
  return labels[value.toLowerCase()] ?? 'Motif non répertorié'
}

function cycleDateLabel(value: string | null): string {
  return value ? `Dernier cycle le ${formatDateTime(value)}` : 'Aucun cycle enregistré'
}

function formatCount(value: number): string {
  return new Intl.NumberFormat('fr-CH').format(value)
}

function formatDate(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return 'date indisponible'
  return new Intl.DateTimeFormat('fr-CH', { dateStyle: 'medium', timeZone: 'Europe/Zurich' }).format(parsed)
}

function formatDateTime(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return 'date indisponible'
  return new Intl.DateTimeFormat('fr-CH', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Europe/Zurich',
  }).format(parsed)
}

function formatOptionalMoney(minorUnits: number | null, currency: string | null): string {
  if (minorUnits === null || !currency) return 'Montant non renseigné'
  return formatMoney(minorUnits, currency)
}

function formatMoney(minorUnits: number, currency: string): string {
  try {
    return new Intl.NumberFormat('fr-CH', {
      style: 'currency',
      currency,
      maximumFractionDigits: 2,
    }).format(minorUnits / 100)
  } catch {
    return `${formatCount(minorUnits / 100)} ${currency}`
  }
}
