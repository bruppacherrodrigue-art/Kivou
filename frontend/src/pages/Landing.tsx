import { useEffect, useState } from 'react'
import { useI18n } from '../i18n'
import { ButtonLink } from '../components/Button'
import { Card, SectionHeading } from '../components/Surfaces'
import { ArrowRightIcon, CheckIcon, ShieldIcon } from '../assets/Icons'
import { billing } from '../api/endpoints'
import type { PlanCatalogue } from '../api/types'
import { marketingCopy } from '../content/marketingCopy'
import styles from './Landing.module.css'

export function Landing() {
  const { locale, money, t } = useI18n()
  const copy = marketingCopy(locale).landing
  const [catalogue, setCatalogue] = useState<PlanCatalogue | null>(null)

  useEffect(() => {
    let active = true
    billing.plans().then((value) => active && setCatalogue(value)).catch(() => undefined)
    return () => { active = false }
  }, [])

  return (
    <>
      <section className={styles.hero}>
        <div className={styles.heroInner}>
          <div className={styles.heroText}>
            <p className={styles.heroEyebrow}>{copy.eyebrow}</p>
            <h1 className={styles.h1}>{copy.title}</h1>
            <p className={styles.heroLead}>{copy.lead}</p>
            <div className={styles.heroActions}>
              <ButtonLink to="/signup?plan=discovery" size="lg" icon={<ArrowRightIcon />}>
                {copy.primary}
              </ButtonLink>
              <ButtonLink to="/exemple-de-signal" variant="secondary" size="lg">
                {copy.secondary}
              </ButtonLink>
            </div>
            <p className={styles.heroTrust}><ShieldIcon />{copy.trust}</p>
          </div>

          <Card as="article" padding="lg" className={styles.featuredSignal}>
            <div className={styles.signalTopline}>
              <span>{copy.signalEyebrow}</span>
              <span><CheckIcon />{copy.verified}</span>
            </div>
            <strong className={styles.signalCompany}>H. Hüther GmbH</strong>
            <p className={styles.signalAmountLabel}>{copy.awarded}</p>
            <strong className={styles.signalAmount}>5,22 M€</strong>
            <p className={styles.signalBody}>{copy.signalBody}</p>
            <dl className={styles.signalFacts}>
              <div><dt>{copy.start}</dt><dd>{copy.startDate}</dd></div>
              <div><dt>{copy.source}</dt><dd>TED 568562-2026</dd></div>
            </dl>
            <ButtonLink to="/exemple-de-signal" variant="secondary">
              {copy.signalAction}
            </ButtonLink>
          </Card>
        </div>
        <div className={styles.signalContents}>
          <strong>{copy.includedLabel}</strong><span>{copy.included}</span>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionInner}>
          <div className={styles.dashboardIntro}>
            <SectionHeading eyebrow={copy.dashboardEyebrow} title={copy.dashboardTitle} lead={copy.dashboardLead} />
            <ButtonLink to="/exemple-de-signal" variant="secondary">{copy.dashboardAction}</ButtonLink>
          </div>
          <ol className={styles.processList} aria-label={copy.dashboardTitle}>
            {copy.reading.map(([title, body], index) => (
              <li className={styles.processStep} key={title}>
                <span className={styles.processNumber}>{String(index + 1).padStart(2, '0')}</span>
                <h3>{title}</h3><p>{body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionInner}>
          <SectionHeading eyebrow={copy.questionsEyebrow} title={copy.questionsTitle} />
          <div className={styles.questionGrid}>
            {copy.questions.map(([eyebrow, title, body]) => (
              <Card as="article" padding="lg" key={title} className={styles.questionCard}>
                <p className={styles.eyebrow}>{eyebrow}</p><h3>{title}</h3><p>{body}</p>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.methodSection}`} id="comment" tabIndex={-1}>
        <div className={styles.sectionInner}>
          <SectionHeading eyebrow={copy.methodEyebrow} title={copy.methodTitle} />
          <ol className={styles.methodList}>
            {copy.method.map(([title, body], index) => (
              <li key={title}><span>{String(index + 1).padStart(2, '0')}</span><strong>{title}</strong><p>{body}</p></li>
            ))}
          </ol>
          <ButtonLink to="/produit" variant="secondary">{copy.methodAction}</ButtonLink>
        </div>
      </section>

      <section className={styles.section} id="tarifs" tabIndex={-1}>
        <div className={`${styles.sectionInner} ${styles.offersOverview}`}>
          <div className={styles.offersCopy}>
            <SectionHeading eyebrow={copy.offersEyebrow} title={copy.offersTitle} lead={copy.offersLead} />
            <div className={styles.heroActions}>
              <ButtonLink to="/signup?plan=discovery">{copy.offersPrimary}</ButtonLink>
              <ButtonLink to="/tarifs" variant="secondary">{copy.offersSecondary}</ButtonLink>
            </div>
          </div>
          {catalogue ? (
            <ul className={styles.offerMatrix} aria-label={locale === 'fr' ? 'Aperçu des offres Kivou' : 'Kivou plan overview'}>
              {catalogue.plans.map((plan) => {
                const currency = catalogue.currencies[0] ?? 'chf'
                const price = plan.monthly_price[currency]
                return (
                  <li key={plan.plan_code}>
                    <span>
                      <strong>{t.billing.plans[plan.plan_code]}</strong>
                      <small>{t.billing.planPositioning[plan.plan_code]}</small>
                    </span>
                    <b>{price ? money(price.amount_minor_units, price.currency) : t.billing.free}</b>
                  </li>
                )
              })}
            </ul>
          ) : null}
        </div>
      </section>
    </>
  )
}
