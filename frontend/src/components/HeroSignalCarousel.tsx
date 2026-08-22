import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { ArrowRightIcon, CheckIcon, ClockIcon, NeedIcon } from '../assets/Icons'
import { landingHeroSignals } from '../content/landingHeroSignals'
import { interpolate, useI18n } from '../i18n'
import { Badge, Card } from './Surfaces'
import styles from './HeroSignalCarousel.module.css'

const AUTOPLAY_DELAY_MS = 7_000
const MANUAL_READING_DELAY_MS = 10_000
const SWIPE_THRESHOLD_PX = 48

export function HeroSignalCarousel() {
  const { locale, t } = useI18n()
  const copy = t.landing.heroCarousel
  const total = landingHeroSignals.length
  const rootRef = useRef<HTMLDivElement>(null)
  const pointerStartX = useRef<number | null>(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const [direction, setDirection] = useState<1 | -1>(1)
  const [userPaused, setUserPaused] = useState(false)
  const [manualReadingPause, setManualReadingPause] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [focusWithin, setFocusWithin] = useState(false)
  const [isVisible, setIsVisible] = useState(true)
  const [pageVisible, setPageVisible] = useState(true)
  const [reducedMotion, setReducedMotion] = useState(false)
  const [announcement, setAnnouncement] = useState('')

  const activeSignal = landingHeroSignals[activeIndex]
  const nextSignal = landingHeroSignals[(activeIndex + 1) % total]

  const announce = useCallback(
    (index: number) => {
      setAnnouncement(
        interpolate(copy.manualAnnouncement, {
          current: index + 1,
          total,
          company: landingHeroSignals[index].companyName,
        }),
      )
    },
    [copy.manualAnnouncement, total],
  )

  const goTo = useCallback(
    (index: number, nextDirection: 1 | -1, manual = true) => {
      const wrappedIndex = (index + total) % total
      setDirection(nextDirection)
      setActiveIndex(wrappedIndex)
      if (manual) {
        setManualReadingPause(true)
        announce(wrappedIndex)
      }
    },
    [announce, total],
  )

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReducedMotion(media.matches)
    update()
    media.addEventListener?.('change', update)
    return () => media.removeEventListener?.('change', update)
  }, [])

  useEffect(() => {
    if (typeof document === 'undefined') return
    const update = () => setPageVisible(document.visibilityState === 'visible')
    update()
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])

  useEffect(() => {
    const root = rootRef.current
    if (!root || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      ([entry]) => setIsVisible(entry.isIntersecting && entry.intersectionRatio >= 0.35),
      { threshold: [0, 0.35] },
    )
    observer.observe(root)
    return () => observer.disconnect()
  }, [])

  const canAutoplay =
    !reducedMotion && !userPaused && !hovered && !focusWithin && isVisible && pageVisible

  useEffect(() => {
    if (!canAutoplay) return
    const timeout = window.setTimeout(
      () => {
        setDirection(1)
        setActiveIndex((current) => (current + 1) % total)
        setManualReadingPause(false)
      },
      manualReadingPause ? MANUAL_READING_DELAY_MS : AUTOPLAY_DELAY_MS,
    )
    return () => window.clearTimeout(timeout)
  }, [activeIndex, canAutoplay, manualReadingPause, total])

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      goTo(activeIndex + 1, 1)
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault()
      goTo(activeIndex - 1, -1)
    } else if (event.key === 'Home') {
      event.preventDefault()
      goTo(0, -1)
    } else if (event.key === 'End') {
      event.preventDefault()
      goTo(total - 1, 1)
    }
  }

  const handleTouchStart = (event: React.TouchEvent<HTMLDivElement>) => {
    pointerStartX.current = event.changedTouches[0]?.clientX ?? null
  }

  const handleTouchEnd = (event: React.TouchEvent<HTMLDivElement>) => {
    if (pointerStartX.current === null) return
    const endX = event.changedTouches[0]?.clientX
    if (endX === undefined) return
    const distance = endX - pointerStartX.current
    pointerStartX.current = null
    if (Math.abs(distance) < SWIPE_THRESHOLD_PX) return
    goTo(activeIndex + (distance < 0 ? 1 : -1), distance < 0 ? 1 : -1)
  }

  const currentLabel = String(activeIndex + 1).padStart(2, '0')
  const totalLabel = String(total).padStart(2, '0')

  return (
    <div
      ref={rootRef}
      className={styles.carousel}
      role="region"
      aria-roledescription="carousel"
      aria-label={copy.regionLabel}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocusCapture={() => setFocusWithin(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocusWithin(false)
      }}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
      onTouchCancel={() => {
        pointerStartX.current = null
      }}
    >
      <div className={styles.viewport}>
        <div className={styles.peek} aria-hidden="true">
          <span>{nextSignal.companyName}</span>
          <strong>{nextSignal.amountAndLocation[locale]}</strong>
        </div>

        <Card
          key={activeSignal.id}
          padding="lg"
          className={`${styles.card} ${direction === 1 ? styles.enterNext : styles.enterPrevious}`}
          as="article"
        >
          <div className={styles.cardTopline}>
            <p className={styles.eventLabel}>{copy.eventLabel}</p>
            <p className={`${styles.count} kivou-tabular`} aria-label={interpolate(copy.slide, { current: activeIndex + 1, total })}>
              {currentLabel} / {totalLabel}
            </p>
          </div>

          <div className={styles.titleBlock}>
            <h2 className={styles.signalTitle}>{activeSignal.headline[locale]}</h2>
            <p className={`${styles.amountLocation} kivou-tabular`}>
              {activeSignal.amountAndLocation[locale]}
            </p>
          </div>

          <p className={styles.summary}>{activeSignal.summary[locale]}</p>

          <div className={styles.insights}>
            <section className={styles.insight} aria-labelledby={`opportunity-${activeSignal.id}`}>
              <span className={styles.insightIcon} aria-hidden="true">
                <NeedIcon />
              </span>
              <div>
                <h3 id={`opportunity-${activeSignal.id}`}>{copy.opportunityLabel}</h3>
                <p>{activeSignal.opportunity[locale]}</p>
              </div>
            </section>
            <section className={styles.insight} aria-labelledby={`timing-${activeSignal.id}`}>
              <span className={styles.insightIcon} aria-hidden="true">
                <ClockIcon />
              </span>
              <div>
                <h3 id={`timing-${activeSignal.id}`}>{copy.timingLabel}</h3>
                <p>{activeSignal.timing[locale]}</p>
              </div>
            </section>
          </div>

          <div className={styles.cardFooter}>
            <ul className={styles.badges} aria-label={`${activeSignal.companyName} — ${copy.sourceVerified}`}>
              <li><Badge tone="brand">{activeSignal.strength[locale]}</Badge></li>
              <li><Badge tone="positive">{activeSignal.timingBadge[locale]}</Badge></li>
              <li><Badge tone="neutral">{activeSignal.country[locale]}</Badge></li>
              <li title={`${activeSignal.sourceSystem} ${activeSignal.sourceNotice}`}>
                <Badge tone="muted">
                  <CheckIcon />
                  {activeSignal.sourceSystem} · {copy.sourceVerified}
                </Badge>
              </li>
            </ul>

            <Link to={activeSignal.detailUrl} className={styles.signalLink}>
              {copy.viewSignal}
              <ArrowRightIcon aria-hidden="true" />
            </Link>
          </div>
        </Card>
      </div>

      <div className={styles.controls}>
        <div className={styles.arrowControls}>
          <button
            type="button"
            className={styles.controlButton}
            aria-label={copy.previous}
            onClick={() => goTo(activeIndex - 1, -1)}
          >
            <span aria-hidden="true">←</span>
          </button>
          <button
            type="button"
            className={styles.controlButton}
            aria-label={copy.next}
            onClick={() => goTo(activeIndex + 1, 1)}
          >
            <span aria-hidden="true">→</span>
          </button>
        </div>

        <div className={styles.indicators}>
          {landingHeroSignals.map((signal, index) => (
            <button
              key={signal.id}
              type="button"
              className={`${styles.indicator} ${index === activeIndex ? styles.indicatorActive : ''}`}
              aria-label={interpolate(copy.indicator, { current: index + 1, total })}
              aria-current={index === activeIndex ? 'true' : undefined}
              onClick={() => goTo(index, index >= activeIndex ? 1 : -1)}
            >
              <span aria-hidden="true" />
            </button>
          ))}
        </div>

        <button
          type="button"
          className={styles.controlButton}
          aria-label={userPaused || reducedMotion ? copy.resume : copy.pause}
          aria-pressed={userPaused}
          disabled={reducedMotion}
          title={reducedMotion ? copy.reducedMotion : undefined}
          onClick={() => {
            setUserPaused((paused) => !paused)
            setManualReadingPause(false)
          }}
        >
          <span aria-hidden="true">{userPaused || reducedMotion ? '▶' : 'Ⅱ'}</span>
        </button>
      </div>

      <p className="kivou-visually-hidden" aria-live="polite" aria-atomic="true">
        {announcement}
      </p>
    </div>
  )
}
