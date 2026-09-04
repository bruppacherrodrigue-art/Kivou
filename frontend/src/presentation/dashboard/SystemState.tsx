import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { ReferenceLink } from '../router/ReferenceLink'
import { KivouBrand } from './AuthShell'

export interface SystemStateAction {
  label: string
  href: string
}

export function SystemState({
  icon: Icon,
  eyebrow,
  title,
  description,
  primary,
  secondary,
  children,
}: {
  icon: LucideIcon
  eyebrow: string
  title: string
  description: ReactNode
  primary?: SystemStateAction
  secondary?: SystemStateAction
  children?: ReactNode
}) {
  return (
    <main className="system-state-page" id="kivou-main">
      <ReferenceLink className="system-state-brand" href="/">
        <KivouBrand subtitle="Marchés attribués · signaux étayés" />
      </ReferenceLink>
      <section className="system-state-card">
        <span className="system-state-icon"><Icon aria-hidden="true" /></span>
        <p className="section-label">{eyebrow}</p>
        <h1>{title}</h1>
        {typeof description === 'string' ? <p>{description}</p> : description}
        {children}
        {primary || secondary ? (
          <div className="system-state-actions">
            {primary ? <ReferenceLink className="public-cta" href={primary.href}>{primary.label}</ReferenceLink> : null}
            {secondary ? <ReferenceLink className="marketing-secondary" href={secondary.href}>{secondary.label}</ReferenceLink> : null}
          </div>
        ) : null}
      </section>
    </main>
  )
}
