import { forwardRef } from 'react'
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { LinkProps } from 'react-router-dom'
import styles from './Button.module.css'

/* Les variantes de la directive §9.
 *
 * `danger` est réservé aux actions réellement destructives. La directive le
 * dit explicitement à propos d'« Ignorer » : une action neutre ne se peint pas
 * en rouge. Aucun bouton de cette application n'utilise `danger` — il existe
 * pour le jour où une action détruira vraiment quelque chose.
 */
export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'quiet' | 'danger'
export type ButtonSize = 'md' | 'lg'

interface CommonProps {
  variant?: ButtonVariant
  size?: ButtonSize
  fullWidth?: boolean
  loading?: boolean
  /** Icône décorative rendue avant le libellé. Jamais seule : un bouton à
   *  icône sans nom accessible est interdit par la directive. */
  icon?: ReactNode
  children: ReactNode
}

type ButtonProps = CommonProps & ButtonHTMLAttributes<HTMLButtonElement>

function classesFor({ variant = 'primary', size = 'md', fullWidth, loading }: CommonProps) {
  return [
    styles.button,
    styles[variant],
    styles[size],
    fullWidth ? styles.fullWidth : '',
    loading ? styles.loading : '',
  ]
    .filter(Boolean)
    .join(' ')
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant, size, fullWidth, loading = false, icon, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      // Le chargement désactive l'action sans retirer le bouton du flux, et
      // `aria-busy` le dit aux technologies d'assistance.
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={classesFor({ variant, size, fullWidth, loading, children })}
      {...rest}
    >
      {icon ? (
        <span className={styles.icon} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {/* Le libellé conserve sa largeur pendant le chargement : la directive
          interdit qu'un bouton rétrécisse en cours d'action. */}
      <span className={styles.label}>{children}</span>
      {loading ? <span className={styles.spinner} aria-hidden="true" /> : null}
    </button>
  )
})

type ButtonLinkProps = CommonProps & Omit<LinkProps, 'children'>

/** Un lien qui a l'apparence d'un bouton — et qui reste un lien.
 *  Ce qui navigue est un `<a>`, ce qui agit est un `<button>` (§38). */
export function ButtonLink({
  variant,
  size,
  fullWidth,
  icon,
  children,
  ...rest
}: ButtonLinkProps) {
  return (
    <Link className={classesFor({ variant, size, fullWidth, children })} {...rest}>
      {icon ? (
        <span className={styles.icon} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <span className={styles.label}>{children}</span>
    </Link>
  )
}

type ButtonAnchorProps = CommonProps & AnchorHTMLAttributes<HTMLAnchorElement>

/** A non-router link styled as a button. This is intentionally separate from
 * `ButtonExternalLink`: a `mailto:` action must not open a blank browser tab. */
export function ButtonAnchor({
  variant,
  size,
  fullWidth,
  icon,
  children,
  ...rest
}: ButtonAnchorProps) {
  return (
    <a className={classesFor({ variant, size, fullWidth, children })} {...rest}>
      {icon ? (
        <span className={styles.icon} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <span className={styles.label}>{children}</span>
    </a>
  )
}

/** Un lien externe stylé en bouton. `noopener` est systématique : une cible
 *  `_blank` sans lui donne à la page ouverte une référence à la nôtre. */
export function ButtonExternalLink({
  variant,
  size,
  fullWidth,
  icon,
  children,
  href,
}: CommonProps & { href: string }) {
  return (
    <a
      className={classesFor({ variant, size, fullWidth, children })}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
    >
      {icon ? (
        <span className={styles.icon} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <span className={styles.label}>{children}</span>
    </a>
  )
}
