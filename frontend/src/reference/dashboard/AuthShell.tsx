import type { ReactNode } from 'react'
import { ArrowLeft, Check } from 'lucide-react'
import { ReferenceLink } from '../router/ReferenceLink'

export function KivouMark() {
  return (
    <span className="kivou-mark" aria-hidden="true">
      <span />
      <span />
      <span />
      <span />
    </span>
  )
}

export function KivouBrand({ subtitle = 'Signaux commerciaux' }: { subtitle?: string }) {
  return (
    <span className="kivou-brand-lockup">
      <KivouMark />
      <span>
        <strong>KIVOU</strong>
        <small>{subtitle}</small>
      </span>
    </span>
  )
}

export function AuthShell({
  eyebrow,
  title,
  description,
  children,
  wide = false,
  showBrand = true,
  navigationDisabled = false,
}: {
  eyebrow: string
  title: string
  description: string
  children: ReactNode
  wide?: boolean
  showBrand?: boolean
  navigationDisabled?: boolean
}) {
  const blockNavigation = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (navigationDisabled) event.preventDefault()
  }

  return (
    <main
      className={`auth-page auth-shell${showBrand ? '' : ' auth-page-no-brand'}`}
      id="kivou-main"
    >
      {showBrand ? (
        <ReferenceLink className="auth-brand" href="/login" aria-label="Kivou, connexion" aria-disabled={navigationDisabled || undefined} onClick={blockNavigation}>
          <KivouBrand subtitle="Veille des marchés attribués" />
        </ReferenceLink>
      ) : null}

      <section className={`auth-card${wide ? ' auth-card-wide' : ''}`}>
        <ReferenceLink className="auth-back-link" href="/" aria-disabled={navigationDisabled || undefined} onClick={blockNavigation}>
          <ArrowLeft aria-hidden="true" /> Retour au site
        </ReferenceLink>
        <div className="auth-heading">
          <p className="section-label">{eyebrow}</p>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        {children}
      </section>

      <aside className="auth-trust" aria-label="Principes Kivou">
        <span><Check aria-hidden="true" /> Faits sourcés</span>
        <span><Check aria-hidden="true" /> Hypothèses signalées</span>
        <span><Check aria-hidden="true" /> Sources et provenances séparées</span>
      </aside>
    </main>
  )
}
