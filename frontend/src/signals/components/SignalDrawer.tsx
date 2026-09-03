import { useId } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { PlausibleNeed, UnifiedStatus, UnlockedFeedItem } from '../../api/types'
import { interpolate, useI18n } from '../../i18n'
import { MatchDots } from './MatchDots'
import { StatusPill } from './StatusPill'
import { MISSING, placeLabel, signalObject } from './SignalRow'
import styles from './signals.module.css'

/** Le nombre de raisons, et de besoins, que le tiroir montre. Au-delà, on ne
 *  lit plus. */
const MAX_ITEMS = 3

function Fact({
  label,
  className,
  children,
}: {
  label: string
  className?: string
  children: ReactNode
}) {
  return (
    <>
      <dt>{label}</dt>
      <dd className={className}>{children}</dd>
    </>
  )
}

/* Les besoins que le marché IMPLIQUE, dans l'ordre où ils servent le lecteur :
 * ceux que son profil vise d'abord, l'ordre du backend ensuite. Un besoin sans
 * libellé n'est pas affichable ; il sort. */
function orderedNeeds(needs: PlausibleNeed[]): PlausibleNeed[] {
  const named = needs.filter((need) => need.label !== null)
  const targeted = named.filter((need) => need.targeted_by_your_profile)
  const rest = named.filter((need) => !need.targeted_by_your_profile)
  return [...targeted, ...rest].slice(0, MAX_ITEMS)
}

export function SignalDrawer({
  item,
  loading,
  error,
  onClose,
  onContacted,
  onSave,
  onIgnore,
  busy,
}: {
  item: UnlockedFeedItem | null
  loading: boolean
  error: unknown | null
  onClose: () => void
  onContacted: () => void
  onSave: () => void
  onIgnore: () => void
  busy: boolean
}) {
  const { t, locale, amount, date } = useI18n()
  const copy = t.signalsTable.drawer
  const titleId = useId()

  if (loading) {
    return (
      <aside className={styles.drawer} aria-label={copy.loading}>
        <div className={styles.skeleton} role="status" aria-label={copy.loading}>
          <span className={styles.skeletonLine} />
          <span className={styles.skeletonLine} />
          <span className={styles.skeletonLine} />
        </div>
      </aside>
    )
  }

  if (error) {
    return (
      <aside className={styles.drawer} aria-label={copy.error}>
        <div className={styles.drawerNotice} role="alert">
          <p>{copy.error}</p>
          <p>{t.common.retry}</p>
        </div>
      </aside>
    )
  }

  if (!item) {
    return (
      <aside className={styles.drawer} aria-label={copy.select}>
        <p className={styles.drawerEmpty}>{copy.select}</p>
      </aside>
    )
  }

  const title = signalObject(item)
  const objectLine = item.factual_display.object_short ?? item.contract.title ?? null
  const money = amount(item.contract.amount?.value, item.contract.amount?.currency)
  const reasons = item.analysis.fit.reasons.slice(0, MAX_ITEMS)
  const needs = orderedNeeds(item.analysis.plausible_needs.items)

  /* Trois horloges, une seule vérité affichée : l'attribution prime, la
   * notification la remplace, la publication ferme la marche. L'intitulé
   * change avec l'horloge — présenter une date de publication comme une date
   * d'attribution serait un mensonge de plus dans un métier qui n'en supporte
   * aucun. */
  const dates = item.contract.dates
  const clock = dates.award
    ? { label: copy.awardedOn, value: dates.award }
    : dates.contract_notification
      ? { label: copy.notifiedOn, value: dates.contract_notification }
      : dates.publication
        ? { label: copy.publishedOn, value: dates.publication }
        : { label: copy.awardedOn, value: null }

  const actions: {
    status: UnifiedStatus
    action: string
    state: string
    onClick: () => void
    primary: boolean
  }[] = [
    {
      status: 'contacted',
      action: copy.contact,
      state: copy.contacted,
      onClick: onContacted,
      primary: true,
    },
    { status: 'saved', action: copy.save, state: copy.saved, onClick: onSave, primary: false },
    {
      status: 'ignored',
      action: copy.ignore,
      state: copy.ignored,
      onClick: onIgnore,
      primary: false,
    },
  ]

  const sourceText = interpolate(copy.source, {
    system: item.source.system ?? MISSING,
    notice: item.source.notice_id ?? '',
  }).trimEnd()

  return (
    <aside
      className={styles.drawer}
      aria-labelledby={titleId}
      data-signal-key={item.signal_id}
    >
      <div className={styles.drawerHead}>
        <StatusPill status={item.status} />
        <MatchDots item={item} />
        <button type="button" className={styles.drawerClose} onClick={onClose}>
          {copy.close}
        </button>
      </div>

      <h2 className={styles.drawerTitle} id={titleId}>
        {title ?? MISSING}
      </h2>
      {objectLine && objectLine !== title ? (
        <p className={styles.drawerObject}>{objectLine}</p>
      ) : null}

      <dl className={styles.facts}>
        <Fact label={copy.winner}>
          {item.company.name === null ? (
            MISSING
          ) : item.company_key ? (
            <Link className={styles.factLink} to={`/app/companies/${item.company_key}`}>
              {item.company.name}
            </Link>
          ) : (
            item.company.name
          )}
        </Fact>
        <Fact label={copy.buyer}>{item.contract.buyer?.name ?? MISSING}</Fact>
        <Fact label={copy.amount} className={styles.factAmount}>
          {money ?? MISSING}
        </Fact>
        <Fact label={copy.place}>{placeLabel(item.contract.location, locale)}</Fact>
        <Fact label={clock.label}>{date(clock.value) ?? MISSING}</Fact>
        <Fact label={copy.cpv}>{item.contract.cpv ?? MISSING}</Fact>
      </dl>

      {needs.length > 0 ? (
        <section className={styles.needs}>
          <h3 className="section-label">{copy.needs}</h3>
          <ul>
            {needs.map((need) => (
              <li key={`${need.category ?? 'need'}-${need.label}`}>
                {need.timing_label ? `${need.label} · ${need.timing_label}` : need.label}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {reasons.length > 0 ? (
        <section className={styles.why}>
          <h3 className="section-label">{copy.why}</h3>
          <ul>
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className={styles.actions}>
        {actions.map((action) =>
          item.status === action.status ? (
            <button
              key={action.status}
              type="button"
              className={styles.actionState}
              data-state={action.status}
              disabled
            >
              {action.state} ✓
            </button>
          ) : (
            <button
              key={action.status}
              type="button"
              className={action.primary ? styles.actionPrimary : styles.action}
              disabled={busy}
              onClick={action.onClick}
            >
              {action.action}
            </button>
          ),
        )}
      </div>

      {item.source.url ? (
        <a
          className={`${styles.source} source-link`}
          href={item.source.url}
          target="_blank"
          rel="noopener noreferrer"
        >
          {sourceText} ↗
        </a>
      ) : (
        <p className={styles.source}>{sourceText}</p>
      )}
    </aside>
  )
}
