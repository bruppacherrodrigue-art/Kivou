import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../App'
import { landingHeroSignals } from '../content/landingHeroSignals'
import { mockApi, renderApp, UNAUTHENTICATED } from '../test/harness'

let observedElement: Element | null = null
let intersectionCallback: IntersectionObserverCallback | null = null

class VisibleIntersectionObserver implements IntersectionObserver {
  readonly root = null
  readonly rootMargin = '0px'
  readonly thresholds = [0.35]
  private readonly callback: IntersectionObserverCallback

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
    intersectionCallback = callback
  }

  disconnect() {}
  observe(target: Element) {
    observedElement = target
    this.callback(
      [
        {
          boundingClientRect: target.getBoundingClientRect(),
          intersectionRatio: 1,
          intersectionRect: target.getBoundingClientRect(),
          isIntersecting: true,
          rootBounds: null,
          target,
          time: 0,
        },
      ],
      this,
    )
  }
  takeRecords() {
    return []
  }
  unobserve() {}
}

function emitIntersection(isIntersecting: boolean) {
  if (!intersectionCallback || !observedElement) throw new Error('IntersectionObserver non initialisé')
  const rect = observedElement.getBoundingClientRect()
  intersectionCallback(
    [
      {
        boundingClientRect: rect,
        intersectionRatio: isIntersecting ? 1 : 0,
        intersectionRect: isIntersecting ? rect : new DOMRectReadOnly(),
        isIntersecting,
        rootBounds: null,
        target: observedElement,
        time: 0,
      },
    ],
    {} as IntersectionObserver,
  )
}

function stubMotion(reduced: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation(() => ({
      matches: reduced,
      media: '(prefers-reduced-motion: reduce)',
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  )
}

beforeEach(() => {
  observedElement = null
  intersectionCallback = null
  mockApi({})
  vi.stubGlobal('IntersectionObserver', VisibleIntersectionObserver)
  stubMotion(false)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('hero de la page d’accueil', () => {
  it('rend une promesse fixe, ses deux CTA et le premier signal dans le HTML initial', () => {
    renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })

    expect(
      screen.getByRole('heading', {
        level: 1,
        name: 'Les entreprises qui remportent des contrats publics — et les occasions commerciales que votre équipe peut examiner.',
      }),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(screen.getByText('SIGNAUX COMMERCIAUX ISSUS DES MARCHÉS PUBLICS')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Voir mes 3 signaux' })).toHaveAttribute('href', '/signup')
    expect(screen.getByRole('link', { name: 'Découvrir un signal complet' })).toHaveAttribute(
      'href',
      '/exemple-de-signal',
    )
    expect(
      screen.getByText('Suisse + Union européenne · Sources officielles · Preuves vérifiables'),
    ).toBeInTheDocument()

    const carousel = screen.getByRole('region', { name: 'Exemples de signaux commerciaux' })
    expect(within(carousel).getByText('01 / 04')).toBeInTheDocument()
    expect(within(carousel).getByRole('heading', { name: /H\. Hüther GmbH remporte/ })).toBeInTheDocument()
    expect(within(carousel).getByText('5,22 M€ · Munich, Allemagne')).toBeInTheDocument()
    expect(within(carousel).getByRole('link', { name: 'Voir le signal' })).toHaveAttribute(
      'href',
      '/exemple-de-signal',
    )
  })

  it('présente exactement quatre signaux publics sourcés dans une fixture dédiée', () => {
    expect(landingHeroSignals).toHaveLength(4)
    expect(landingHeroSignals.map((signal) => signal.companyName)).toEqual([
      'H. Hüther GmbH',
      'PKE Electronics AG',
      'Heinrich Würfel Metallbau GmbH',
      'CRAM',
    ])
    expect(
      landingHeroSignals.every(
        (signal) =>
          signal.sourceUrl.startsWith('https://ted.europa.eu/') ||
          signal.sourceUrl.startsWith('https://www.simap.ch/'),
      ),
    ).toBe(true)
    expect(new Set(landingHeroSignals.map((signal) => signal.sourceNotice)).size).toBe(4)
    const publicProjection = JSON.stringify(landingHeroSignals)
    expect(publicProjection).not.toMatch(/acquisition engine|target_icp|score|band|locked|lead|email/i)
    expect(publicProjection).not.toMatch(/récent|recent|maintenant|now|timing favorable|favourable timing/i)
    expect(landingHeroSignals.every((signal) => signal.strength.fr === 'Angle commercial plausible')).toBe(true)
    expect(landingHeroSignals.every((signal) => signal.strength.en === 'Plausible sales angle')).toBe(true)
  })

  it('navigue avec les flèches, les indicateurs et le clavier sans déplacer le H1', () => {
    renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
    const carousel = screen.getByRole('region', { name: 'Exemples de signaux commerciaux' })
    const h1 = screen.getByRole('heading', { level: 1 })

    fireEvent.click(within(carousel).getByRole('button', { name: 'Signal suivant' }))
    expect(within(carousel).getByText('02 / 04')).toBeInTheDocument()
    expect(within(carousel).getByRole('heading', { name: /PKE Electronics AG remporte/ })).toBeInTheDocument()

    fireEvent.click(within(carousel).getByRole('button', { name: 'Afficher le signal 4 sur 4' }))
    expect(within(carousel).getByText('04 / 04')).toBeInTheDocument()
    expect(within(carousel).getByRole('heading', { name: /CRAM remporte/ })).toBeInTheDocument()

    fireEvent.keyDown(carousel, { key: 'ArrowLeft' })
    expect(within(carousel).getByText('03 / 04')).toBeInTheDocument()
    fireEvent.keyDown(carousel, { key: 'Home' })
    expect(within(carousel).getByText('01 / 04')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1 })).toBe(h1)
  })

  it('tourne après sept secondes et respecte le contrôle pause/reprise', () => {
    vi.useFakeTimers()
    renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
    const carousel = screen.getByRole('region', { name: 'Exemples de signaux commerciaux' })

    act(() => vi.advanceTimersByTime(7_000))
    expect(within(carousel).getByText('02 / 04')).toBeInTheDocument()

    fireEvent.click(within(carousel).getByRole('button', { name: 'Mettre le carrousel en pause' }))
    act(() => vi.advanceTimersByTime(14_000))
    expect(within(carousel).getByText('02 / 04')).toBeInTheDocument()

    fireEvent.click(within(carousel).getByRole('button', { name: 'Reprendre le carrousel' }))
    act(() => vi.advanceTimersByTime(7_000))
    expect(within(carousel).getByText('03 / 04')).toBeInTheDocument()
  })

  it('désactive la rotation automatique quand le mouvement est réduit', () => {
    vi.useFakeTimers()
    stubMotion(true)
    renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
    const carousel = screen.getByRole('region', { name: 'Exemples de signaux commerciaux' })

    act(() => vi.advanceTimersByTime(21_000))
    expect(within(carousel).getByText('01 / 04')).toBeInTheDocument()
    expect(within(carousel).getByRole('button', { name: 'Reprendre le carrousel' })).toBeDisabled()
  })

  it('suspend la rotation hors du viewport et lorsque le carrousel reçoit le focus', () => {
    vi.useFakeTimers()
    renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
    const carousel = screen.getByRole('region', { name: 'Exemples de signaux commerciaux' })

    act(() => emitIntersection(false))
    act(() => vi.advanceTimersByTime(14_000))
    expect(within(carousel).getByText('01 / 04')).toBeInTheDocument()

    act(() => emitIntersection(true))
    fireEvent.focus(carousel)
    act(() => vi.advanceTimersByTime(7_000))
    expect(within(carousel).getByText('01 / 04')).toBeInTheDocument()

    fireEvent.blur(carousel, { relatedTarget: null })
    act(() => vi.advanceTimersByTime(7_000))
    expect(within(carousel).getByText('02 / 04')).toBeInTheDocument()
  })

  it('permet de changer de signal par un geste tactile', () => {
    renderApp(<AppRoutes />, { route: '/', session: UNAUTHENTICATED })
    const carousel = screen.getByRole('region', { name: 'Exemples de signaux commerciaux' })

    fireEvent.touchStart(carousel, { changedTouches: [{ clientX: 280 }] })
    fireEvent.touchEnd(carousel, { changedTouches: [{ clientX: 120 }] })

    expect(within(carousel).getByText('02 / 04')).toBeInTheDocument()
  })

  it('localise intégralement le contenu fixe et les quatre signaux en anglais', () => {
    const { container } = renderApp(<AppRoutes />, {
      route: '/',
      locale: 'en',
      session: UNAUTHENTICATED,
    })

    expect(
      screen.getByRole('heading', {
        level: 1,
        name: 'The companies winning public contracts — and the sales opportunities your team can assess.',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('SALES SIGNALS FROM PUBLIC CONTRACT AWARDS')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'See my 3 signals' })).toHaveAttribute('href', '/signup')
    expect(screen.getByRole('link', { name: 'Explore a complete signal' })).toHaveAttribute(
      'href',
      '/exemple-de-signal',
    )

    const carousel = screen.getByRole('region', { name: 'Sales signal examples' })
    fireEvent.click(within(carousel).getByRole('button', { name: 'Show signal 4 of 4' }))
    expect(within(carousel).getByText('Maintenance capacity, energy systems and specialist support')).toBeInTheDocument()
    expect(container).not.toHaveTextContent('Occasion commerciale')
    expect(container).not.toHaveTextContent('Pourquoi maintenant')
  })
})
