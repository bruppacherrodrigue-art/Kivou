import type { ReactNode } from 'react'
import styles from './ScreenChrome.module.css'

/** Header and segments extracted from Signals; label/value row from Today. */
export function ScreenHeader({ title, description, level = 1, id }: {
  title: ReactNode
  description?: ReactNode
  level?: 1 | 2
  id?: string
}) {
  const Heading = level === 1 ? 'h1' : 'h2'
  return <header className={styles.header} data-ui="screen-header">
    <Heading id={id}>{title}</Heading>
    {description ? <p>{description}</p> : null}
  </header>
}

export function ScreenSegments({ children, label, navigation = false, className = '' }: {
  children: ReactNode
  label: string
  navigation?: boolean
  className?: string
}) {
  const Tag = navigation ? 'nav' : 'div'
  return <Tag className={`${styles.segments} ${className}`} data-ui="screen-segments"
    role={navigation ? undefined : 'group'} aria-label={label}>{children}</Tag>
}

export function SummaryRow({ label, value, definition = false }: {
  label: ReactNode
  value: ReactNode
  definition?: boolean
}) {
  if (value === null || value === undefined || value === '') return null
  return <div className={styles.row} data-ui="summary-row">
    {definition ? <><dt>{label}</dt><dd>{value}</dd></> : <><span>{label}</span><b>{value}</b></>}
  </div>
}
