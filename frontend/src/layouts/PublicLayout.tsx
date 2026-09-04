import { useEffect, useRef } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { useI18n } from '../i18n'
import { ReferenceLink } from '../presentation/router/ReferenceLink'
import { SurfaceBoundary } from '../presentation/surface/SurfaceBoundary'
import { HashTarget } from './HashTarget'

export function Logo() {
  return (
    <ReferenceLink className="brand" href="/" aria-label="Kivou, accueil">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <g fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="50" cy="50" r="12" />
          <path d="M50 19v19M50 62v19M19 50h19M62 50h19M28 28l13.5 13.5M58.5 58.5 72 72M72 28 58.5 41.5M41.5 58.5 28 72" />
          <circle cx="85" cy="64" r="2.2" fill="currentColor" stroke="none" /><circle cx="65" cy="85" r="2.2" fill="currentColor" stroke="none" /><circle cx="35" cy="85" r="2.2" fill="currentColor" stroke="none" /><circle cx="15" cy="65" r="2.2" fill="currentColor" stroke="none" /><circle cx="15" cy="35" r="2.2" fill="currentColor" stroke="none" /><circle cx="35" cy="15" r="2.2" fill="currentColor" stroke="none" /><circle cx="65" cy="15" r="2.2" fill="currentColor" stroke="none" /><circle cx="85" cy="35" r="2.2" fill="currentColor" stroke="none" />
        </g>
      </svg>
      <span className="brand-copy"><span className="brand-name">KIVOU</span><span className="brand-tag">Signaux commerciaux</span></span>
    </ReferenceLink>
  )
}

const nav = [['accueil', '/', 'Accueil'], ['produit', '/produit', 'Comment ça marche'], ['signal', '/exemple-de-signal', 'Exemple de signal'], ['tarifs', '/tarifs', 'Tarifs'], ['contact', '/contact', 'Contact']] as const

export function SiteHeader({ active }: { active?: string }) {
  const { key } = useLocation()
  const mobileMenu = useRef<HTMLDetailsElement>(null)

  useEffect(() => {
    if (mobileMenu.current) mobileMenu.current.open = false
  }, [key])

  return (
    <header className="site-header"><nav className="site-nav container" aria-label="Navigation principale"><Logo />
      <ul className="nav-links">{nav.map(([key, href, label]) => <li key={key}><ReferenceLink href={href} aria-current={active === key ? 'page' : undefined}>{label}</ReferenceLink></li>)}</ul>
      <div className="nav-actions"><ReferenceLink className="btn secondary compact-btn" href="/login">Se connecter</ReferenceLink><ReferenceLink className="btn primary compact-btn" href="/signup?plan=discovery">Essayer gratuitement</ReferenceLink><details ref={mobileMenu} className="mobile-menu" onClick={(event) => {
        if (event.target instanceof Element && event.target.closest('a')) event.currentTarget.open = false
      }}><summary aria-label="Ouvrir le menu"><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 7h16M4 12h16M4 17h16" /></svg></summary><nav aria-label="Navigation mobile">{nav.map(([key, href, label]) => <ReferenceLink key={key} href={href} aria-current={active === key ? 'page' : undefined}>{label}</ReferenceLink>)}<ReferenceLink href="/login">Se connecter</ReferenceLink><ReferenceLink className="mobile-signup" href="/signup?plan=discovery">Essayer gratuitement</ReferenceLink></nav></details></div>
    </nav></header>
  )
}

export function SiteFooter() {
  return (
    <footer className="site-footer"><div className="footer-inner"><div className="footer-grid"><div className="footer-brand"><Logo /><p>Les marchés attribués deviennent des comptes à examiner, avec les faits et le calendrier sous les yeux.</p></div><nav className="footer-col" aria-label="Produit"><strong>Produit</strong><ul><li><ReferenceLink href="/produit">Comment ça marche</ReferenceLink></li><li><ReferenceLink href="/exemple-de-signal">Exemple de signal</ReferenceLink></li><li><ReferenceLink href="/tarifs">Tarifs</ReferenceLink></li></ul></nav><nav className="footer-col" aria-label="Compte"><strong>Compte</strong><ul><li><ReferenceLink href="/signup?plan=discovery">Créer un compte</ReferenceLink></li><li><ReferenceLink href="/login">Se connecter</ReferenceLink></li><li><ReferenceLink href="/contact">Nous contacter</ReferenceLink></li></ul></nav><nav className="footer-col" aria-label="Informations"><strong>Informations</strong><ul><li><ReferenceLink href="/informations-legales#mentions-legales">Mentions légales</ReferenceLink></li><li><ReferenceLink href="/informations-legales#confidentialite">Confidentialité</ReferenceLink></li><li><ReferenceLink href="/informations-legales#cgu">Conditions générales</ReferenceLink></li></ul></nav></div><div className="footer-bottom"><span>© 2026 Kivou. Tous droits réservés.</span><span>Sources officielles accessibles. Couverture européenne.</span></div></div></footer>
  )
}

function activePublicRoute(pathname: string) {
  if (pathname === '/') return 'accueil'
  if (pathname === '/produit') return 'produit'
  if (pathname === '/exemple-de-signal') return 'signal'
  if (pathname === '/tarifs') return 'tarifs'
  if (pathname === '/contact') return 'contact'
  return undefined
}

export function PublicLayout() {
  const { pathname, hash } = useLocation()
  const { locale } = useI18n()
  const previousPathname = useRef(pathname)

  useEffect(() => {
    document.documentElement.lang = 'fr'
    return () => { document.documentElement.lang = locale }
  }, [locale])

  useEffect(() => {
    const pathnameChanged = previousPathname.current !== pathname
    previousPathname.current = pathname
    if (pathnameChanged && !hash) window.scrollTo(0, 0)
  }, [hash, pathname])

  return (
    <SurfaceBoundary surface="public">
      <a className="skip-link" href="#main">Aller au contenu</a>
      <SiteHeader active={activePublicRoute(pathname)} />
      <HashTarget />
      <Outlet />
      <SiteFooter />
    </SurfaceBoundary>
  )
}
