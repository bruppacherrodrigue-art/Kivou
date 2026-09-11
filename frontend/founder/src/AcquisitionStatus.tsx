import type { FounderAcquisitionStatus } from './types'

interface Props {
  status: FounderAcquisitionStatus
  compact?: boolean
}

const MODE_LABELS: Record<string, string> = {
  SHADOW: 'Mode observation',
  ASSISTED: 'Mode assisté',
  AUTONOMOUS_CAPPED: 'Mode autonome plafonné',
  ADAPTIVE_VOLUME: 'Volume adaptatif',
}

const CYCLE_STATUS_LABELS: Record<string, string> = {
  SUPPRESSED: 'Supprimé',
  SUCCEEDED: 'Réussi',
  FAILED: 'Échoué',
}

const CYCLE_REASON_LABELS: Record<string, string> = {
  NO_ELIGIBLE_OPPORTUNITY: 'Aucune opportunité éligible',
  VERIFIED_CONTACT_NOT_FOUND: 'Aucun contact vérifié trouvé',
  ACQUISITION_DISABLED: 'Acquisition désactivée',
  CYCLE_TIME_BUDGET_REACHED: 'Limite de temps du cycle atteinte',
  CURRENT_RUN_INTERRUPTED: 'Cycle interrompu',
  CURRENT_RUN_TECHNICAL_FAILURE: 'Échec technique du cycle',
  OPERATOR_ABANDONED: 'Cycle abandonné par l’opérateur',
  RUNTIME_CYCLE_REASON_INVALID: 'Motif du cycle indisponible',
  DAILY_PENDING_CAP_REACHED: 'Limite quotidienne de cibles en attente atteinte',
}

export function AcquisitionStatus({ status, compact = false }: Props) {
  return (
    <section
      className={compact ? 'control-runtime control-runtime--compact' : 'control-runtime'}
      aria-label="État de l’acquisition"
    >
      <div>
        <span>Mode</span>
        <strong>{modeLabel(status.mode)}</strong>
      </div>
      <div>
        <span>Activité</span>
        <strong>{activityLabel(status)}</strong>
      </div>
      <div>
        <span>Dernier cycle</span>
        <strong>{cycleLabel(status)}</strong>
      </div>
      <div>
        <span>Résultat</span>
        <strong>{cycleResultLabel(status)}</strong>
      </div>
    </section>
  )
}

function modeLabel(mode: string | null): string {
  if (!mode) return 'Mode inconnu'
  return MODE_LABELS[mode] ?? 'Mode inconnu'
}

function activityLabel(status: FounderAcquisitionStatus): string {
  if (status.activity === 'UNKNOWN') return 'État indisponible'
  const label = status.activity === 'RUNNING' ? 'Actif' : 'Arrêté'
  return status.activity_since
    ? `${label} depuis le ${formatDateTime(status.activity_since)}`
    : `${label} · date de début indisponible`
}

function cycleLabel(status: FounderAcquisitionStatus): string {
  if (!status.last_cycle_ref && !status.last_cycle_at) return 'Aucun cycle observé'
  const reference = cycleReferenceLabel(status.last_cycle_ref)
  const observedAt = status.last_cycle_at
    ? formatDateTime(status.last_cycle_at)
    : 'date indisponible'
  return `${reference} · ${observedAt}`
}

function cycleReferenceLabel(reference: string | null): string {
  if (!reference) return 'Référence indisponible'
  if (reference.length <= 24) return reference
  return `${reference.slice(0, 8)}…${reference.slice(-6)}`
}

function cycleResultLabel(status: FounderAcquisitionStatus): string {
  if (!status.last_cycle_status) return 'Aucun résultat observé'
  const result = CYCLE_STATUS_LABELS[status.last_cycle_status] ?? 'Résultat inconnu'
  const reason = status.last_cycle_reason_code
    ? CYCLE_REASON_LABELS[status.last_cycle_reason_code]
      ?? 'Motif non répertorié'
    : 'Aucun motif signalé'
  return `${result} · ${reason}`
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
