import type { Fit } from '../../api/types'
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

/* Les niveaux dérivés du seul libellé de fit, faute de bande.
 *
 * `GET /signals` n'expose pas encore `icp_match_band` (écart API 1). Tant
 * qu'il ne l'expose pas, quatre points pleins sont IMPOSSIBLES : une dérivée
 * ne peut pas prétendre à la certitude d'une mesure. C'est pourquoi le maximum
 * dérivé est 3, et pourquoi la dérivation se voit dans `data-derived`. */
const LABEL_LEVELS: Record<string, Filled> = {
  matched_needs: 3,
  territory_only: 2,
  targeted_profile: 1,
}

/** Le nombre de points pleins, et s'il a été DÉDUIT plutôt que mesuré. */
export function matchLevel(fit: Fit): { filled: Filled; derived: boolean } {
  if (fit.band) return { filled: BAND_LEVELS[fit.band], derived: false }
  return { filled: LABEL_LEVELS[fit.label] ?? 1, derived: true }
}

export function MatchDots({ fit }: { fit: Fit }) {
  const { t } = useI18n()
  const { filled, derived } = matchLevel(fit)

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
