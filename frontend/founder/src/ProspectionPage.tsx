import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { AcquisitionStatus, cycleResultLabel } from './AcquisitionStatus'
import {
  approveFounderProspect,
  correctFounderProspect,
  FounderApiError,
  loadFounderProspectSend,
  loadFounderProspectionActions,
  prepareFounderProspection,
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
  FounderProspectionSendProgress,
} from './types'

const SEND_REQUEST_STORAGE_KEY = 'founder-prospection-send-request-id'
const TERMINAL_SEND_STATUSES = new Set<FounderProspectionSendProgress['status']>([
  'completed',
  'partial',
  'failed',
])

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

const CONSUMER_MAILBOX_DOMAINS = new Set([
  'free.fr',
  'gmail.com',
  'googlemail.com',
  'hotmail.com',
  'hotmail.fr',
  'icloud.com',
  'laposte.net',
  'live.com',
  'live.fr',
  'mac.com',
  'me.com',
  'msn.com',
  'orange.fr',
  'outlook.com',
  'outlook.fr',
  'proton.me',
  'protonmail.com',
  'wanadoo.fr',
  'yahoo.com',
  'yahoo.fr',
])

function isConsumerMailbox(address: string): boolean {
  const separator = address.lastIndexOf('@')
  return separator >= 0 && CONSUMER_MAILBOX_DOMAINS.has(address.slice(separator + 1).trim().toLowerCase())
}

const DIRECTORY_STATUS_LABELS: Record<FounderDirectoryStatus, string> = {
  confirmed_domain: 'Domaine confirmé',
  without_website: 'Sans site',
  reverification_required: 'À revérifier',
}

const REVERIFICATION_REASON_LABELS: Record<string, string> = {
  email_below_threshold: 'E-mail sous le seuil',
  website_below_threshold: 'Site sous le seuil',
  legacy_domain_not_validated: 'Ancien domaine non validé',
  model_confidence_below_threshold: 'Confiance modèle insuffisante',
  no_website: 'Sans site confirmé',
  placeholder_email: 'Adresse factice',
  instantly_bounce: 'Rejet Instantly',
  founder_wrong_address: 'Adresse écartée',
  blocked_domain_audit: 'Domaine bloqué',
}

type ProspectionPageProps = {
  data: FounderProspection
  filters: FounderProspectionFilters
  refreshing: boolean
  onFiltersChange: (filters: FounderProspectionFilters) => void
  onRefresh: () => void
}

export function ProspectionPage({
  data,
  filters,
  refreshing,
  onFiltersChange,
  onRefresh,
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
        onRefresh={onRefresh}
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
}: Omit<ProspectionPageProps, 'onRefresh'>) {
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

      <div className="prospection-enrichment" role="region" aria-label="Enrichissement">
        <div>
          <p className="control-panel-kicker">Enrichissement</p>
          <div className="prospection-enrichment-metrics">
            <CompactMetric label="Fiches aujourd’hui" value={directory.enrichment.enriched_today_count} />
            <CompactMetric label="Fiches cette semaine" value={directory.enrichment.enriched_week_count} />
            <div className="prospection-inline-list">
              <small>Modèle</small>
              <strong>{modelLabel(directory.enrichment.model)}</strong>
            </div>
            <div className="prospection-inline-list">
              <small>Coût cumulé</small>
              <strong>{formatUsd(directory.enrichment.cumulative_cost_usd)}</strong>
            </div>
            <div className="prospection-inline-list">
              <small>Dernière passe</small>
              <strong>{formatUsd(directory.enrichment.latest_batch_cost_usd)}</strong>
              <span>
                {formatCount(directory.enrichment.latest_batch_call_count)} appels ·{' '}
                {formatCount(directory.enrichment.latest_batch_input_tokens)} tokens entrée
              </span>
            </div>
          </div>
        </div>
        <div className="prospection-review-reasons">
          <small>À revérifier par motif</small>
          {directory.reverification_reason_counts.length === 0 ? (
            <span>Aucune fiche à revérifier.</span>
          ) : directory.reverification_reason_counts.map((reason) => (
            <button
              key={reason.key}
              type="button"
              aria-pressed={filters.reverification_reason === reason.key}
              disabled={refreshing}
              onClick={() => changeFilter({
                status: 'reverification_required',
                reverification_reason: reason.key,
              })}
            >
              {reverificationReasonLabel(reason.key)} · {formatCount(reason.count)}
            </button>
          ))}
        </div>
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
          onChange={(value) => changeFilter({
            status: value as FounderDirectoryStatus | '',
            reverification_reason: '',
          })}
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
  onRefresh,
  onOpenMail,
}: {
  data: FounderProspection
  onRefresh: () => void
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
  const [sendProgress, setSendProgress] = useState<FounderProspectionSendProgress | null>(null)
  const [activeSendRequestId, setActiveSendRequestId] = useState<string | null>(() => (
    sessionStorage.getItem(SEND_REQUEST_STORAGE_KEY)
  ))
  const [actionError, setActionError] = useState<string | null>(null)
  const [pollingWarning, setPollingWarning] = useState<string | null>(null)
  const [reconciliationWarning, setReconciliationWarning] = useState<string | null>(null)
  const [sendSubmitting, setSendSubmitting] = useState(false)
  const [terminalReconciling, setTerminalReconciling] = useState(false)
  const [preparationState, setPreparationState] = useState<'idle' | 'requesting' | 'polling'>('idle')
  const preparationBaselineRef = useRef<string | null>(null)
  const sendProgressRef = useRef<FounderProspectionSendProgress | null>(null)
  const sendItemOverlayRef = useRef(new Map<string, FounderProspectionSendProgress['items'][number]>())
  const activeSendRequestRef = useRef<string | null>(sessionStorage.getItem(SEND_REQUEST_STORAGE_KEY))
  const sendSubmittingRef = useRef(false)
  const terminalReconciliationRequestRef = useRef<string | null>(null)
  const listGenerationRef = useRef(0)
  const listRequestControllerRef = useRef<AbortController | null>(null)
  const loadMoreControllerRef = useRef<AbortController | null>(null)
  const mountedRef = useRef(true)
  const preparationStartedAtRef = useRef<number | null>(null)
  const preparationSawRunningRef = useRef(false)
  const preparationGeneratedAtRef = useRef<string | null>(null)

  const acquisition = data.acquisition_status
  const preparationRunning = preparationState !== 'idle' || acquisition.activity === 'RUNNING'
  const preparationAtCap = acquisition.prepared_today_count >= acquisition.daily_pending_cap

  const activateSendRequest = useCallback((requestId: string | null) => {
    activeSendRequestRef.current = requestId
    setActiveSendRequestId(requestId)
  }, [])

  const applySendOverlay = useCallback((targets: FounderProspectionActionTarget[]) => (
    targets.map((target) => {
      const overlay = sendItemOverlayRef.current.get(target.target_id)
      return overlay?.status === 'sent'
        ? { ...target, status: 'sent' as const, acceptance_error: null }
        : target
    })
  ), [])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      listRequestControllerRef.current?.abort()
      loadMoreControllerRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    if (preparationState !== 'polling') return undefined
    if (acquisition.activity === 'RUNNING') preparationSawRunningRef.current = true
    const cycleCompleted = acquisition.last_cycle_at !== preparationBaselineRef.current
    const returnedToStopped = preparationSawRunningRef.current && acquisition.activity === 'STOPPED'
    const refreshedAfterLaunch = data.generated_at !== preparationGeneratedAtRef.current
    const fastCycleCompleted = refreshedAfterLaunch && acquisition.activity === 'STOPPED'
    if (cycleCompleted || returnedToStopped || fastCycleCompleted || preparationAtCap) {
      setPreparationState('idle')
      return undefined
    }
    if (
      preparationStartedAtRef.current !== null
      && Date.now() - preparationStartedAtRef.current >= 25 * 60 * 1000
    ) {
      setPreparationState('idle')
      setActionError('La préparation prend plus de temps que prévu. Actualise la page pour vérifier son état.')
      return undefined
    }
    const interval = window.setInterval(onRefresh, 2_000)
    return () => window.clearInterval(interval)
  }, [
    acquisition.activity,
    acquisition.last_cycle_at,
    data.generated_at,
    onRefresh,
    preparationAtCap,
    preparationState,
  ])

  const prepareQueue = async () => {
    if (preparationRunning || preparationAtCap) return
    setPreparationState('requesting')
    setActionError(null)
    preparationBaselineRef.current = acquisition.last_cycle_at
    preparationStartedAtRef.current = Date.now()
    preparationSawRunningRef.current = false
    preparationGeneratedAtRef.current = data.generated_at
    try {
      await prepareFounderProspection()
      setPreparationState('polling')
      onRefresh()
    } catch (error) {
      setPreparationState('idle')
      setActionError(founderActionErrorMessage(error, 'La préparation de la file a échoué.'))
    }
  }

  const refreshQueue = useCallback(async () => {
    const generation = ++listGenerationRef.current
    listRequestControllerRef.current?.abort()
    loadMoreControllerRef.current?.abort()
    const controller = new AbortController()
    listRequestControllerRef.current = controller
    const activeSignal = controller.signal
    const [pending, approved] = await Promise.all([
      loadFounderProspectionActions('pending_review', activeSignal),
      loadFounderProspectionActions('approved', activeSignal),
    ])
    if (activeSignal.aborted || generation !== listGenerationRef.current) return false
    const merged = [...pending.items, ...approved.items]
    setItems(applySendOverlay(merged.filter((item, index) => (
      merged.findIndex((candidate) => candidate.target_id === item.target_id) === index
    ))))
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
    return true
  }, [applySendOverlay])

  useEffect(() => {
    setLoaded(false)
    setActionError(null)
    void refreshQueue().catch((error: unknown) => {
      if (mountedRef.current) {
        setLoaded(true)
        setActionError(founderActionErrorMessage(error, 'Impossible de charger la file de prospection.'))
      }
    })
    return undefined
  }, [data.generated_at, refreshQueue])

  const reconcileSendProgress = useCallback((progress: FounderProspectionSendProgress) => {
    const mergedItems = new Map(sendItemOverlayRef.current)
    for (const item of progress.items) mergedItems.set(item.target_id, item)
    sendItemOverlayRef.current = mergedItems
    setItems((current) => applySendOverlay(current))
    const mergedProgress = { ...progress, items: [...mergedItems.values()] }
    sendProgressRef.current = mergedProgress
    setSendProgress(mergedProgress)
  }, [applySendOverlay])

  useEffect(() => {
    if (!activeSendRequestId || sendSubmittingRef.current) return undefined
    if (
      sendProgressRef.current?.request_id === activeSendRequestId
      && TERMINAL_SEND_STATUSES.has(sendProgressRef.current.status)
    ) return undefined
    const controller = new AbortController()
    let timer: number | undefined
    let stopped = false

    const poll = async () => {
      try {
        const progress = await loadFounderProspectSend(activeSendRequestId, controller.signal)
        if (stopped || controller.signal.aborted) return
        if (
          progress.request_id !== activeSendRequestId
          || sessionStorage.getItem(SEND_REQUEST_STORAGE_KEY) !== activeSendRequestId
        ) {
          setPollingWarning('La progression reçue ne correspond pas à la requête en cours.')
          timer = window.setTimeout(() => void poll(), 2_000)
          return
        }
        // Item errors are retained in sendProgress; this clears only a transient polling warning.
        setPollingWarning(null)
        reconcileSendProgress(progress)
        if (!TERMINAL_SEND_STATUSES.has(progress.status)) {
          timer = window.setTimeout(() => void poll(), 2_000)
        }
      } catch (error) {
        if (stopped || controller.signal.aborted) return
        if (error instanceof FounderApiError && error.status === 404) {
          setPollingWarning(founderActionErrorMessage(error, 'La requête d’envoi est introuvable.'))
          if (
            activeSendRequestRef.current === activeSendRequestId
            && sessionStorage.getItem(SEND_REQUEST_STORAGE_KEY) === activeSendRequestId
          ) {
            sessionStorage.removeItem(SEND_REQUEST_STORAGE_KEY)
            activateSendRequest(null)
          }
          return
        }
        setPollingWarning(founderActionErrorMessage(
          error,
          'La progression de l’envoi est momentanément indisponible. Réessaie dans un instant.',
        ))
        timer = window.setTimeout(() => void poll(), 2_000)
      }
    }

    void poll()
    return () => {
      stopped = true
      controller.abort()
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [activeSendRequestId, activateSendRequest, reconcileSendProgress])

  useEffect(() => {
    if (
      activeSendRequestId
      && sendProgress?.request_id === activeSendRequestId
      && TERMINAL_SEND_STATUSES.has(sendProgress.status)
    ) {
      if (terminalReconciliationRequestRef.current === activeSendRequestId) return undefined
      // This runs after React commits terminal progress, then refreshes authoritative target versions
      // before allowing any retry or row mutation.
      terminalReconciliationRequestRef.current = activeSendRequestId
      setTerminalReconciling(true)
      let retryTimer: number | undefined
      let cancelled = false
      const reconcile = async () => {
        try {
          const refreshed = await refreshQueue()
          if (!refreshed || cancelled) return
          if (
            mountedRef.current
            && activeSendRequestRef.current === activeSendRequestId
            && sessionStorage.getItem(SEND_REQUEST_STORAGE_KEY) === activeSendRequestId
          ) {
            setReconciliationWarning(null)
            sessionStorage.removeItem(SEND_REQUEST_STORAGE_KEY)
            activateSendRequest(null)
            setTerminalReconciling(false)
          }
        } catch (error: unknown) {
          if (!cancelled) {
            setReconciliationWarning(founderActionErrorMessage(
              error,
              'Impossible d’actualiser la file après l’envoi. Nouvelle tentative en cours.',
            ))
            retryTimer = window.setTimeout(() => void reconcile(), 2_000)
          }
        }
      }
      void reconcile()
      return () => {
        cancelled = true
        listRequestControllerRef.current?.abort()
        if (retryTimer !== undefined) window.clearTimeout(retryTimer)
      }
    }
    return undefined
  }, [activeSendRequestId, activateSendRequest, refreshQueue, sendProgress])

  const loadMore = async () => {
    if (loadingMore) return
    const generation = ++listGenerationRef.current
    listRequestControllerRef.current?.abort()
    loadMoreControllerRef.current?.abort()
    const controller = new AbortController()
    loadMoreControllerRef.current = controller
    const requests: Array<Promise<{
      status: 'pending_review' | 'approved'
      response: Awaited<ReturnType<typeof loadFounderProspectionActions>>
    }>> = []
    for (const status of ['pending_review', 'approved'] as const) {
      const page = queuePages[status].next
      if (page !== null) {
        requests.push(loadFounderProspectionActions(status, controller.signal, page)
          .then((response) => ({ status, response })))
      }
    }
    if (requests.length === 0) return
    setLoadingMore(true)
    setActionError(null)
    try {
      const pages = await Promise.all(requests)
      if (controller.signal.aborted || generation !== listGenerationRef.current) return
      setItems((current) => {
        const merged = [...current, ...pages.flatMap(({ response }) => response.items)]
        return applySendOverlay(merged.filter((item, index) => (
          merged.findIndex((candidate) => candidate.target_id === item.target_id) === index
        )))
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
      if (!controller.signal.aborted && generation === listGenerationRef.current) {
        setActionError(founderActionErrorMessage(error, 'Impossible de charger la suite de la file.'))
      }
    } finally {
      if (generation === listGenerationRef.current) setLoadingMore(false)
    }
  }

  const refreshAfterStatusMutation = async () => {
    const hasUnloadedPages = queuePages.pending_review.remaining > 0
      || queuePages.approved.remaining > 0
    if (!hasUnloadedPages) return
    try {
      await refreshQueue()
    } catch {
      setQueuePages({
        pending_review: { next: null, remaining: 0 },
        approved: { next: null, remaining: 0 },
      })
      setActionError('La décision est enregistrée, mais la file n’a pas pu être actualisée. Recharge la page.')
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
      await refreshAfterStatusMutation()
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
    const currentTarget = items.find((item) => item.target_id === target.target_id)
    if (!currentTarget) {
      setCorrectingTarget(null)
      setActionError('Cette cible a été actualisée. Rouvre sa fiche avant de la modifier.')
      return false
    }
    target = currentTarget
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
      await refreshAfterStatusMutation()
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
    const currentTarget = items.find((item) => item.target_id === target.target_id)
    if (!currentTarget) {
      setRejectingTarget(null)
      setActionError('Cette cible a été actualisée. Rouvre sa fiche avant de l’écarter.')
      return false
    }
    target = currentTarget
    setActionError(null)
    setBusyTargetIds((current) => new Set(current).add(target.target_id))
    setItems((current) => current.map((item) => item.target_id === target.target_id
      ? { ...item, status: 'rejected', version: item.version + 1 }
      : item))
    try {
      await rejectFounderProspect(target.target_id, target.version, reason, comment)
      await refreshAfterStatusMutation()
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
  const approvedItems = items.filter((item) => item.status === 'approved')
  const approvedCount = approvedItems.length
  const heldApprovedCount = approvedItems.filter((item) => isConsumerMailbox(item.email.address)).length
  const eligibleApprovedCount = approvedCount - heldApprovedCount
  const sendBatchCount = Math.min(eligibleApprovedCount, 25)
  const remainingQueueCount = queuePages.pending_review.remaining + queuePages.approved.remaining
  const visibleItems = items.filter((item) => (
    (item.status === 'pending_review' || item.status === 'approved' || item.status === 'sent')
    && !isConsumerMailbox(item.email.address)
  ))
  const heldItems = items.filter((item) => (
    (item.status === 'pending_review' || item.status === 'approved' || item.status === 'sent')
    && isConsumerMailbox(item.email.address)
  ))
  const orderedVisibleItems = [...visibleItems, ...heldItems]
  const firstHeldTargetId = heldItems[0]?.target_id
  const sendApproved = async () => {
    const approved = items.filter((item) => (
      item.status === 'approved' && !isConsumerMailbox(item.email.address)
    )).slice(0, 25)
    if (approved.length === 0 || activeSendRequestRef.current || sendSubmittingRef.current) return
    const requestId = crypto.randomUUID()
    sendSubmittingRef.current = true
    setSendSubmitting(true)
    activeSendRequestRef.current = requestId
    sessionStorage.setItem(SEND_REQUEST_STORAGE_KEY, requestId)
    setSendConfirmationOpen(false)
    setActionError(null)
    // A new request must not inherit confirmation states from a prior terminal request.
    sendItemOverlayRef.current.clear()
    sendProgressRef.current = null
    setSendProgress(null)
    try {
      const response = await sendFounderProspects(
        requestId,
        approved.map((item) => ({ target_id: item.target_id, expected_version: item.version })),
      )
      if (
        !mountedRef.current
        || activeSendRequestRef.current !== requestId
        || sessionStorage.getItem(SEND_REQUEST_STORAGE_KEY) !== requestId
      ) return
      if (response.request_id !== requestId) {
        sendSubmittingRef.current = false
        setSendSubmitting(false)
        setActionError('La réponse d’envoi ne correspond pas à la requête en cours.')
        activateSendRequest(requestId)
        return
      }
      sendSubmittingRef.current = false
      setSendSubmitting(false)
      reconcileSendProgress(response)
      activateSendRequest(requestId)
    } catch (error) {
      if (!mountedRef.current || activeSendRequestRef.current !== requestId) return
      sendSubmittingRef.current = false
      setSendSubmitting(false)
      if (error instanceof FounderApiError && error.status >= 400 && error.status < 500) {
        sessionStorage.removeItem(SEND_REQUEST_STORAGE_KEY)
        activateSendRequest(null)
      } else {
        // The POST may have reached the server; resume this persisted request instead of retrying it.
        activateSendRequest(requestId)
      }
      setActionError(
        error instanceof FounderApiError && error.status >= 500
          ? 'Vérification de l’envoi en cours.'
          : founderActionErrorMessage(error, 'L’envoi a échoué.'),
      )
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
        <div className="prospection-preparation-bar">
          <div className="prospection-preparation-facts" aria-label="Planification de la préparation">
            <span>
              Dernier cycle · {acquisition.last_cycle_at
                ? formatDateTime(acquisition.last_cycle_at)
                : 'Aucun cycle observé'}
            </span>
            <span>Résultat · {cycleResultLabel(acquisition)}</span>
            <span>
              Prochain passage · {acquisition.next_run_at
                ? formatDateTime(acquisition.next_run_at)
                : 'Non planifié'}
            </span>
            <span>File · {acquisition.prepared_today_count}/{acquisition.daily_pending_cap}</span>
          </div>
          <button
            type="button"
            className="prospection-action-primary"
            disabled={preparationRunning || preparationAtCap}
            onClick={() => void prepareQueue()}
          >
            Préparer la file du jour
          </button>
        </div>
        {preparationRunning ? (
          <p className="prospection-action-notice" role="status">
            Préparation en cours · {acquisition.prepared_today_count}/{acquisition.daily_pending_cap}
          </p>
        ) : preparationAtCap ? (
          <p className="prospection-action-warning" role="status">
            La file du jour a atteint son plafond de 25 cibles.
          </p>
        ) : null}
        {actionError ? <p className="prospection-action-error" role="alert">{actionError}</p> : null}
        {pollingWarning ? <p className="prospection-action-warning" role="alert">{pollingWarning}</p> : null}
        {reconciliationWarning ? <p className="prospection-action-warning" role="alert">{reconciliationWarning}</p> : null}
        {!loaded ? (
          <div className="prospection-compact-empty">
            <strong>Chargement de la file…</strong>
          </div>
        ) : orderedVisibleItems.length === 0 ? (
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
                  <th>Acceptation fournisseur</th>
                  <th>Livraison SMTP</th>
                </tr>
              </thead>
              <tbody>
                {orderedVisibleItems.map((item) => (
                  <Fragment key={item.target_id}>
                    {item.target_id === firstHeldTargetId ? (
                      <tr className="prospection-mailbox-hold-divider">
                        <th colSpan={9}>{heldItems.length} boîte{heldItems.length === 1 ? '' : 's'} grand public en attente</th>
                      </tr>
                    ) : null}
                    <tr className={item.status === 'approved' ? 'prospection-row-approved' : undefined}>
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
                      {item.status === 'sent' ? (
                        <span>Transmission terminée</span>
                      ) : (
                        <div className="prospection-row-actions">
                          <button
                            type="button"
                            disabled={terminalReconciling || item.status === 'approved' || busyTargetIds.has(item.target_id)}
                            onClick={() => void approve(item)}
                          >
                            {item.status === 'approved' ? 'Validée' : 'Valider'}
                          </button>
                          <button
                            type="button"
                            disabled={terminalReconciling || busyTargetIds.has(item.target_id)}
                            onClick={() => setCorrectingTarget(item)}
                          >
                            Corriger
                          </button>
                          <button
                            type="button"
                            disabled={terminalReconciling || busyTargetIds.has(item.target_id)}
                            onClick={() => setRejectingTarget(item)}
                          >
                            Écarter
                          </button>
                        </div>
                      )}
                    </td>
                    <td>
                      {item.status !== 'sent' && item.acceptance_error ? (
                        <>
                          <span>Échec de vérification</span>
                          <small>{acceptanceErrorLabel(item.acceptance_error)}</small>
                        </>
                      ) : acceptanceStatusLabel(item.status)}
                    </td>
                    <td>{smtpDeliveryStatusLabel(item.delivery.status)}</td>
                    </tr>
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <footer className="prospection-queue-footer">
          <span>
            {heldApprovedCount > 0
              ? `${formatCount(approvedCount)} cibles validées · ${formatCount(eligibleApprovedCount)} éligible${eligibleApprovedCount === 1 ? '' : 's'} · ${formatCount(heldApprovedCount)} en attente`
              : approvedCount === 1 ? '1 cible validée' : `${formatCount(approvedCount)} cibles validées`}
          </span>
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
              disabled={sendBatchCount === 0 || activeSendRequestId !== null || sendSubmitting || terminalReconciling || killSwitchActive}
              aria-label={sendBatchLabel(eligibleApprovedCount, heldApprovedCount)}
              onClick={() => setSendConfirmationOpen(true)}
            >
              {sendBatchLabel(eligibleApprovedCount, heldApprovedCount)}
            </button>
          </div>
        </footer>
        {killSwitchActive ? (
          <p className="prospection-action-warning" role="status">
            Envois suspendus par le coupe-circuit.
          </p>
        ) : null}
        {sendProgress ? (
          <p className="prospection-action-notice" role="status">
            {sendProgressLabel(sendProgress)}
          </p>
        ) : null}
        {sendProgress?.items
          .filter((item) => item.status === 'failed' && item.error_message)
          .map((item) => (
            <p key={item.target_id} className="prospection-action-error" role="alert">
              {item.email_address} — {item.error_message}
            </p>
          ))}
      </article>
      {correctingTarget ? (
        <CorrectionDrawer
          item={correctingTarget}
          busy={terminalReconciling || busyTargetIds.has(correctingTarget.target_id)}
          onClose={() => setCorrectingTarget(null)}
          onSubmit={(changes) => correct(correctingTarget, changes)}
        />
      ) : null}
      {rejectingTarget ? (
        <RejectionDrawer
          item={rejectingTarget}
          busy={terminalReconciling || busyTargetIds.has(rejectingTarget.target_id)}
          onClose={() => setRejectingTarget(null)}
          onSubmit={(reason, comment) => reject(rejectingTarget, reason, comment)}
        />
      ) : null}
      {sendConfirmationOpen ? (
        <SendConfirmationDrawer
          count={sendBatchCount}
          onClose={() => setSendConfirmationOpen(false)}
          onConfirm={() => void sendApproved()}
          busy={sendSubmitting || activeSendRequestId !== null}
        />
      ) : null}
    </section>
  )
}

function sendBatchLabel(approvedCount: number, heldCount = 0): string {
  if (heldCount > 0 && approvedCount === 1) return 'Envoyer la cible professionnelle'
  if (heldCount > 0 && approvedCount > 25) return 'Envoyer les 25 premières cibles professionnelles'
  if (heldCount > 0) return `Envoyer les ${approvedCount} cibles professionnelles`
  if (approvedCount === 1) return 'Envoyer la cible validée'
  if (approvedCount > 25) return 'Envoyer les 25 premières cibles validées'
  return `Envoyer les ${approvedCount} cibles validées`
}

function sendProgressLabel(progress: FounderProspectionSendProgress): string {
  const sent = `${progress.sent_count}/${progress.total_count} envoyée${progress.sent_count === 1 ? '' : 's'}`
  const verificationCount = progress.items.filter((item) => item.status === 'verification_pending').length
  const details = [
    progress.failed_count > 0 ? `${progress.failed_count} en échec` : null,
    verificationCount > 0 ? `${verificationCount} en vérification` : null,
  ].filter((detail): detail is string => detail !== null)
  return details.length > 0 ? `${sent} · ${details.join(' · ')}` : sent
}

function acceptanceStatusLabel(status: FounderProspectionActionTarget['status']): string {
  switch (status) {
    case 'pending_review': return 'En attente de validation'
    case 'approved': return 'Validée, non transmise'
    case 'sent': return 'Acceptée'
    case 'rejected': return 'Écartée'
  }
}

function acceptanceErrorLabel(error: string): string {
  if (error === 'instantly email invalid') {
    return 'Adresse invalide selon la vérification Instantly'
  }
  if (error === 'instantly_account_error') {
    return 'Compte d’envoi Instantly indisponible'
  }
  return error
}

function smtpDeliveryStatusLabel(status: FounderProspectionActionTarget['delivery']['status']): string {
  switch (status) {
    case 'not_sent': return 'Non confirmée'
    case 'delivered': return 'Délivrée'
    case 'opened': return 'Ouverte'
    case 'clicked': return 'Cliquée'
    case 'replied': return 'Réponse reçue'
    case 'bounced': return 'Rejetée'
    case 'unsubscribed': return 'Désinscrite'
  }
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
  busy,
}: {
  count: number
  onClose: () => void
  onConfirm: () => void
  busy: boolean
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
            <button type="button" className="prospection-action-primary" onClick={onConfirm} disabled={busy}>
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
          value={results.mrr_by_currency === null
            ? '—'
            : results.mrr_by_currency.length > 0
              ? results.mrr_by_currency.map((money) => formatMoney(money.minor_units, money.currency)).join(' · ')
              : '0 €'}
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

function reverificationReasonLabel(value: string): string {
  return REVERIFICATION_REASON_LABELS[value] ?? value
    .replaceAll('_', ' ')
    .replace(/^./, (letter) => letter.toUpperCase())
}

function modelLabel(value: string | null): string {
  if (!value) return '—'
  return value
    .split('/').at(-1)!
    .replace(/^claude-/, 'Claude ')
    .replaceAll('-', ' ')
    .replace(/\bsonnet\b/i, 'Sonnet')
}

function formatUsd(value: string): string {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '—'
  return `${new Intl.NumberFormat('fr-CH', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(parsed)} $US`
}

function sourceLabel(value: string | null): string {
  if (!value) return 'Source inconnue'
  const labels: Record<string, string> = {
    apollo: 'Apollo',
    site: 'Site',
    manual: 'Manuel',
    model: 'Modèle',
  }
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
