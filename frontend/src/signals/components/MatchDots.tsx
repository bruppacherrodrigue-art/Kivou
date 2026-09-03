import type { Fit, UnlockedFeedItem } from '../../api/types'
import { interpolate, useI18n } from '../../i18n'
import styles from './signals.module.css'

const DOTS = [1, 2, 3, 4] as const

type Filled = (typeof DOTS)[number]

const BAND_LEVELS: Record<NonNullable<Fit['band']>, Filled> = {
  strong: 4,
  promising: 3,
  weak: 2,
  unknown: 1,
}

/** Le nombre de points pleins, et s'il a été DÉDUIT plutôt que mesuré.
 *
 * `GET /signals` n'expose pas encore `icp_match_band` (écart API 1). Le repli
 * ne lit PAS `analysis.fit.label` : le backend y met une phrase traduite
 * (« Très bon pour votre profil »), pas un code, et toute dérivation par
 * libellé retomberait invariablement sur un point sur quatre. Il lit donc les
 * seuls faits structurés disponibles : un besoin explicitement visé par le
 * profil vaut trois points, un lieu connu deux, le reste un. Une déduction ne
 * peut jamais atteindre quatre points, et elle se signale dans
 * `data-derived`. */
export function matchLevel(item: UnlockedFeedItem): { filled: Filled; derived: boolean } {
  const band = item.analysis.fit.band
  if (band) return { filled: BAND_LEVELS[band], derived: false }
  if (item.analysis.plausible_needs.items.some((need) => need.targeted_by_your_profile)) {
    return { filled: 3, derived: true }
  }
  if (item.contract.location) return { filled: 2, derived: true }
  return { filled: 1, derived: true }
}

export function MatchDots({ item }: { item: UnlockedFeedItem }) {
  const { t } = useI18n()
  const { filled, derived } = matchLevel(item)

  return (
    <span
      className={styles.matchDots}
      role="img"
      aria-label={interpolate(t.signalsTable.match, { count: filled })}
      data-derived={derived ? 'true' : 'false'}
      data-filled={filled}
    >
      {DOTS.map((position) => (
        <i key={position} aria-hidden="true" data-dot={position <= filled ? 'filled' : 'empty'} />
      ))}
    </span>
  )
}
