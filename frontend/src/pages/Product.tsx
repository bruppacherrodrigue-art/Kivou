import { ButtonLink } from '../components/Button'
import { Card, SectionHeading } from '../components/Surfaces'
import { PublicPageMeta } from '../components/PublicPageMeta'
import { marketingCopy } from '../content/marketingCopy'
import { useI18n } from '../i18n'
import styles from './MarketingPage.module.css'

export function Product() {
  const { locale } = useI18n()
  const copy = marketingCopy(locale).product

  return (
    <article className={styles.page}>
      <PublicPageMeta
        title={`${copy.title} — Kivou`}
        description={copy.lead}
        canonicalPath="/produit"
      />

      <header className={styles.hero}>
        <div className={styles.inner}>
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>{copy.eyebrow}</p>
            <h1 className={styles.title}>{copy.title}</h1>
            <p className={styles.lead}>{copy.lead}</p>
            <div className={styles.actions}>
              <ButtonLink to="/signup?plan=discovery" size="lg">{copy.primary}</ButtonLink>
              <ButtonLink to="/exemple-de-signal" variant="secondary" size="lg">{copy.secondary}</ButtonLink>
            </div>
          </div>
          <ol className={styles.journey}>
            {copy.journey.map(([title, body], index) => (
              <li key={title}>
                <Card as="div" padding="lg" className={styles.step}>
                  <span className={styles.stepNumber}>{String(index + 1).padStart(2, '0')}</span>
                  <h3>{title}</h3><p>{body}</p>
                </Card>
              </li>
            ))}
          </ol>
        </div>
      </header>

      <section className={styles.section}>
        <div className={styles.inner}>
          <SectionHeading eyebrow={copy.whyEyebrow} title={copy.whyTitle} lead={copy.whyLead} />
          <div className={styles.distinctions}>
            {copy.distinctions.map(([title, body]) => (
              <Card key={title} as="article" padding="lg" className={styles.distinction}>
                <h3>{title}</h3><p>{body}</p>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionSubtle}`}>
        <div className={styles.inner}>
          <SectionHeading eyebrow={copy.methodEyebrow} title={copy.methodTitle} lead={copy.methodLead} />
          <ol className={styles.method}>
            {copy.method.map(([title, body], index) => (
              <li key={title}>
                <Card as="div" padding="lg" className={styles.step}>
                  <span className={styles.stepNumber}>{String(index + 1).padStart(2, '0')}</span>
                  <h3>{title}</h3><p>{body}</p>
                </Card>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.inner}>
          <SectionHeading eyebrow={copy.caseEyebrow} title={copy.caseTitle} lead={copy.caseLead} />
          <div className={styles.caseGrid}>
            <Card as="article" padding="lg" className={styles.caseCard}>
              <p className={styles.eyebrow}>{copy.factsLabel}</p>
              <h3>H. Hüther GmbH</h3>
              <ul>{copy.facts.map((item) => <li key={item}>{item}</li>)}</ul>
            </Card>
            <Card as="article" padding="lg" className={`${styles.caseCard} ${styles.analysisCard}`}>
              <p className={styles.eyebrow}>{copy.analysisLabel}</p>
              <h3>{copy.examine}</h3>
              <ul>{copy.analysis.map((item) => <li key={item}>{item}</li>)}</ul>
              <ButtonLink to="/exemple-de-signal" variant="secondary">{copy.read}</ButtonLink>
            </Card>
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionSubtle}`}>
        <div className={styles.inner}>
          <SectionHeading eyebrow={copy.timelineEyebrow} title={copy.timelineTitle} lead={copy.timelineLead} />
        </div>
      </section>

      <section className={styles.cta}>
        <div className={styles.inner}>
          <h2>{copy.ctaTitle}</h2><p>{copy.ctaLead}</p>
          <div className={styles.actions}>
            <ButtonLink to="/signup?plan=discovery" size="lg">{copy.primary}</ButtonLink>
            <ButtonLink to="/exemple-de-signal" variant="secondary" size="lg">{copy.secondary}</ButtonLink>
          </div>
        </div>
      </section>
    </article>
  )
}
