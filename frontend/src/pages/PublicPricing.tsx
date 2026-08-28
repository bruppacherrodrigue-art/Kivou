import { useEffect, useState } from 'react'
import { billing } from '../api/endpoints'
import type { PlanCatalogue } from '../api/types'
import { PlanGrid } from '../billing/PlanGrid'
import { ButtonLink } from '../components/Button'
import { PublicPageMeta } from '../components/PublicPageMeta'
import { SectionHeading } from '../components/Surfaces'
import { ShieldIcon } from '../assets/Icons'
import { marketingCopy } from '../content/marketingCopy'
import { useI18n } from '../i18n'
import styles from './MarketingPage.module.css'

export function PublicPricing() {
  const { locale } = useI18n()
  const copy = marketingCopy(locale).pricing
  const [catalogue, setCatalogue] = useState<PlanCatalogue | null>(null)
  const [unavailable, setUnavailable] = useState(false)

  useEffect(() => {
    let active = true
    billing.plans()
      .then((value) => active && setCatalogue(value))
      .catch(() => active && setUnavailable(true))
    return () => { active = false }
  }, [])

  return (
    <article className={styles.page}>
      <PublicPageMeta title={`${copy.title} — Kivou`} description={copy.lead} canonicalPath="/tarifs" />
      <header className={styles.hero}>
        <div className={styles.inner}>
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>{copy.eyebrow}</p>
            <h1 className={styles.title}>{copy.title}</h1>
            <p className={styles.lead}>{copy.lead}</p>
            <p className={styles.trust}><ShieldIcon />{copy.trust}</p>
          </div>
        </div>
      </header>
      <section className={styles.section}>
        <div className={styles.inner}>
          <SectionHeading eyebrow={copy.comparisonEyebrow} title={copy.comparisonTitle} />
          {catalogue ? <PlanGrid catalogue={catalogue} variant="public" /> : null}
          {unavailable ? <p className={styles.lead}>{copy.unavailable}</p> : null}
        </div>
      </section>
      <section className={styles.cta}>
        <div className={styles.inner}>
          <h2>{copy.ctaTitle}</h2><p>{copy.ctaLead}</p>
          <ButtonLink to="/signup?plan=discovery" size="lg">{locale === 'fr' ? 'Commencer gratuitement' : 'Start free'}</ButtonLink>
        </div>
      </section>
    </article>
  )
}
