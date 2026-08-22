import { publicDemoSignal } from '../content/publicDemoSignal'
import { ButtonExternalLink, ButtonLink } from '../components/Button'
import { Badge, Card, DataList, DataRow, SectionHeading } from '../components/Surfaces'
import { interpolate, useI18n } from '../i18n'
import styles from './PublicSignalDemo.module.css'

/**
 * Démonstration publique d'un signal Kivou.
 *
 * La page reste entièrement statique et sans donnée de compte. Sa hiérarchie
 * est volontairement commerciale : opportunité → pertinence → timing → action
 * → preuve → limites. Les faits viennent de la projection vérifiée ci-dessous ;
 * les quatre angles de prospection sont explicitement présentés comme des
 * inférences issues des volumes publiés.
 */
export function PublicSignalDemo() {
  const { t, locale, amount, date } = useI18n()
  const s = publicDemoSignal
  const roundedAmount = amount(s.contract.amount, s.contract.currency)
  const exactAmount = `${new Intl.NumberFormat(locale === 'fr' ? 'fr-FR' : 'en-GB', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(s.contract.amount))} ${s.contract.currency}`

  const quantityLabels = [
    t.publicDemo.quantityWoodDoors,
    t.publicDemo.quantitySteelDoors,
    t.publicDemo.quantitySkirting,
    t.publicDemo.quantityWallCladding,
    t.publicDemo.quantityGlazing,
    t.publicDemo.quantityKitchenettes,
  ]
  const quantities = s.contract.publishedQuantities.map((line, index) => {
    const separator = line.lastIndexOf(' : ')
    return {
      label: quantityLabels[index],
      sourceLabel: separator >= 0 ? line.slice(0, separator) : line,
      value: separator >= 0 ? line.slice(separator + 3) : '',
    }
  })

  const opportunities = [
    {
      title: t.publicDemo.opportunityDoorsTitle,
      body: t.publicDemo.opportunityDoorsBody,
      strength: t.publicDemo.signalStrong,
      tone: 'strong',
    },
    {
      title: t.publicDemo.opportunityWoodTitle,
      body: t.publicDemo.opportunityWoodBody,
      strength: t.publicDemo.signalStrong,
      tone: 'strong',
    },
    {
      title: t.publicDemo.opportunityGlazingTitle,
      body: t.publicDemo.opportunityGlazingBody,
      strength: t.publicDemo.signalTargeted,
      tone: 'targeted',
    },
    {
      title: t.publicDemo.opportunityKitchenTitle,
      body: t.publicDemo.opportunityKitchenBody,
      strength: t.publicDemo.signalTargeted,
      tone: 'targeted',
    },
  ] as const

  const matchingReasons = [
    t.publicDemo.matchingReasonOne,
    t.publicDemo.matchingReasonTwo,
    t.publicDemo.matchingReasonThree,
    t.publicDemo.matchingReasonFour,
    t.publicDemo.matchingReasonFive,
    t.publicDemo.matchingReasonSix,
  ]

  const timeline = [
    { date: date(s.timing.awardDate), label: t.publicDemo.timelineAwarded },
    { date: date(s.timing.publishedAt), label: t.publicDemo.timelinePublished },
    { date: date(s.lastVerifiedAt), label: t.publicDemo.timelineVerified },
    { date: t.publicDemo.timelineNow, label: t.publicDemo.timelineContact, current: true },
    { date: date(s.timing.startDate), label: t.publicDemo.timelineStart },
    { date: date(s.timing.endDate), label: t.publicDemo.timelineEnd },
  ]

  return (
    <div className={styles.page}>
      <section className={styles.hero} aria-labelledby="public-signal-title">
        <div className={styles.heroInner}>
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>{t.publicDemo.heroEyebrow}</p>
            <h1 className={styles.heroTitle} id="public-signal-title">
              {t.publicDemo.heroTitle}
            </h1>
            <p className={styles.heroSubtitle}>{t.publicDemo.heroSubtitle}</p>
            <p className={styles.heroTiming}>{t.publicDemo.heroTiming}</p>

            <div className={styles.badges} aria-label={t.publicDemo.contractSnapshot}>
              <Badge tone="positive">{t.publicDemo.heroBadgeVerified}</Badge>
              <Badge tone="brand">{t.publicDemo.heroBadgeRecent}</Badge>
              <Badge tone="positive">{t.publicDemo.heroBadgeTiming}</Badge>
              <Badge tone="muted">{t.publicDemo.heroBadgeSource}</Badge>
            </div>

            <p className={styles.heroMeta}>
              {interpolate(t.publicDemo.heroMeta, {
                published: date(s.timing.publishedAt) ?? s.timing.publishedAt,
                verified: date(s.lastVerifiedAt) ?? s.lastVerifiedAt,
              })}
            </p>

            <div className={styles.actions}>
              <ButtonLink to="/signup" variant="primary" size="lg">
                {t.publicDemo.heroPrimary}
              </ButtonLink>
              <ButtonExternalLink href={s.sourceUrl} variant="secondary" size="lg">
                {t.publicDemo.heroSecondary}
                <span className="kivou-visually-hidden"> {t.publicDemo.externalNewTab}</span>
              </ButtonExternalLink>
            </div>
          </div>

          <Card className={styles.contractCard} padding="lg" as="aside">
            <p className={styles.contractCardEyebrow}>{t.publicDemo.contractSnapshot}</p>
            <p className={styles.contractAmount}>{roundedAmount}</p>
            <DataList>
              <DataRow label={t.publicDemo.winner}>{s.winner.legalName}</DataRow>
              <DataRow label={t.publicDemo.object}>{s.contract.title}</DataRow>
              <DataRow label={t.publicDemo.buyer}>{s.buyer.legalName}</DataRow>
              <DataRow label={t.publicDemo.place}>
                {s.contract.postalCode} {s.contract.locality} · {t.publicDemo.countryGermany}
              </DataRow>
            </DataList>
          </Card>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="commercial-summary-title">
        <div className={`${styles.sectionInner} ${styles.overviewGrid}`}>
          <SectionHeading
            eyebrow={t.publicDemo.overviewEyebrow}
            title={t.publicDemo.overviewTitle}
            id="commercial-summary-title"
          />
          <div className={styles.overviewBody}>
            <p>{t.publicDemo.overviewBodyOne}</p>
            <p>{t.publicDemo.overviewBodyTwo}</p>
            <p className={styles.overviewHighlight}>{t.publicDemo.overviewHighlight}</p>
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionSubtle}`} aria-labelledby="volumes-title">
        <div className={styles.sectionInner}>
          <SectionHeading
            title={t.publicDemo.volumesTitle}
            lead={t.publicDemo.volumesLead}
            id="volumes-title"
          />
          <ul className={styles.volumeGrid}>
            {quantities.map((quantity) => (
              <li className={styles.volumeCard} key={quantity.sourceLabel}>
                <span className={styles.volumeValue}>{quantity.value}</span>
                <span className={styles.volumeLabel}>{quantity.label}</span>
                <span className={styles.volumeSource}>{quantity.sourceLabel}</span>
              </li>
            ))}
          </ul>
          <p className={styles.sectionNote}>{t.publicDemo.quantitiesNote}</p>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="opportunities-title">
        <div className={styles.sectionInner}>
          <SectionHeading
            title={t.publicDemo.opportunitiesTitle}
            lead={t.publicDemo.opportunitiesLead}
            id="opportunities-title"
          />
          <div className={styles.opportunityGrid}>
            {opportunities.map((opportunity) => (
              <Card
                key={opportunity.title}
                padding="lg"
                as="article"
                className={`${styles.opportunityCard} ${styles[`opportunity-${opportunity.tone}`]}`}
              >
                <Badge tone={opportunity.tone === 'strong' ? 'positive' : 'brand'}>
                  {opportunity.strength}
                </Badge>
                <h3 className={styles.cardTitle}>{opportunity.title}</h3>
                <p className={styles.cardBody}>{opportunity.body}</p>
              </Card>
            ))}
          </div>
          <p className={styles.inferenceNote}>{t.publicDemo.opportunitiesNote}</p>
        </div>
      </section>

      <section className={`${styles.section} ${styles.matchingSection}`} aria-labelledby="matching-title">
        <div className={`${styles.sectionInner} ${styles.matchingGrid}`}>
          <div className={styles.matchingIntro}>
            <p className={styles.eyebrowInverse}>{t.publicDemo.matchingEyebrow}</p>
            <h2 className={styles.matchingTitle} id="matching-title">
              {t.publicDemo.matchingTitle}
            </h2>
            <p className={styles.matchingLead}>{t.publicDemo.matchingIntro}</p>
            <p className={styles.matchingConclusion}>{t.publicDemo.matchingConclusion}</p>
          </div>
          <div>
            <ul className={styles.matchingReasons}>
              {matchingReasons.map((reason) => (
                <li key={reason}>
                  <span className={styles.checkMark} aria-hidden="true">✓</span>
                  <span>{reason}</span>
                </li>
              ))}
            </ul>
            <p className={styles.matchingNote}>{t.publicDemo.matchingNote}</p>
          </div>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="timing-title">
        <div className={styles.sectionInner}>
          <SectionHeading title={t.publicDemo.timingTitle} id="timing-title" />
          <ol className={styles.timeline}>
            {timeline.map((item) => (
              <li className={item.current ? styles.timelineCurrent : ''} key={item.label}>
                <span className={styles.timelineMarker} aria-hidden="true" />
                <span className={styles.timelineDate}>{item.date}</span>
                <span className={styles.timelineLabel}>{item.label}</span>
              </li>
            ))}
          </ol>
          <div className={styles.timingExplanation}>
            <h3>{t.publicDemo.timingWhyTitle}</h3>
            <p>{t.publicDemo.timingBody}</p>
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionSubtle}`} aria-labelledby="action-title">
        <div className={`${styles.sectionInner} ${styles.actionGrid}`}>
          <div className={styles.actionCopy}>
            <SectionHeading
              eyebrow={t.publicDemo.actionEyebrow}
              title={t.publicDemo.actionTitle}
              id="action-title"
            />
            <p>{t.publicDemo.actionBody}</p>
            <div className={styles.actions}>
              <ButtonLink to="/signup" variant="primary" size="lg">
                {t.publicDemo.actionPrimary}
              </ButtonLink>
              <ButtonLink to="/signup" variant="secondary" size="lg">
                {t.publicDemo.actionSecondary}
              </ButtonLink>
            </div>
          </div>
          <blockquote className={styles.outreachExample}>
            <p className={styles.outreachLabel}>{t.publicDemo.actionExampleLabel}</p>
            <p>{t.publicDemo.actionExample}</p>
          </blockquote>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="evidence-title">
        <div className={`${styles.sectionInner} ${styles.evidenceGrid}`}>
          <div className={styles.evidenceIntro}>
            <SectionHeading title={t.publicDemo.evidenceTitle} id="evidence-title" />
            <p>{t.publicDemo.evidenceBody}</p>
            <ButtonExternalLink href={s.sourceUrl} variant="primary" size="lg">
              {t.publicDemo.openSource}
              <span className="kivou-visually-hidden"> {t.publicDemo.externalNewTab}</span>
            </ButtonExternalLink>
            <p className={styles.sourceHint}>{t.publicDemo.openSourceHint}</p>
          </div>
          <Card className={styles.evidenceCard} padding="lg">
            <DataList>
              <DataRow label={t.publicDemo.evidenceCpv} tabular>{s.contract.cpv}</DataRow>
              <DataRow label={t.publicDemo.evidenceAmount} tabular>{exactAmount}</DataRow>
              <DataRow label={t.publicDemo.evidenceLot} tabular>LOT-0000</DataRow>
              <DataRow label={t.publicDemo.evidenceReference} tabular>{s.contract.reference}</DataRow>
              <DataRow label={t.publicDemo.evidenceIdentifier} tabular>{s.winner.identifier.value}</DataRow>
              <DataRow label={t.publicDemo.evidenceSignature} tabular>{date(s.timing.signatureDate)}</DataRow>
            </DataList>
            <details className={styles.technical}>
              <summary className={styles.technicalSummary}>{t.publicDemo.evidenceTechnical}</summary>
              <DataList>
                {s.evidence.map((piece) => (
                  <DataRow
                    key={piece.path}
                    label={piece.pathKind === 'xml' ? t.publicDemo.evidencePathXml : t.publicDemo.evidencePathField}
                  >
                    <span className={styles.path}>{piece.path}</span>
                  </DataRow>
                ))}
              </DataList>
            </details>
          </Card>
        </div>
      </section>

      <section className={`${styles.section} ${styles.coverageSection}`} aria-labelledby="coverage-title">
        <div className={styles.coverageInner}>
          <SectionHeading title={t.publicDemo.coverageTitle} id="coverage-title" />
          <p className={styles.coverageBody}>{t.publicDemo.coverageBody}</p>
          <details className={styles.coverageDetails}>
            <summary>{t.publicDemo.coverageDetails}</summary>
            <DataList>
              <DataRow label={t.publicDemo.coverageEvent}>{t.publicDemo.statusVerified}</DataRow>
              <DataRow label={t.publicDemo.coverageWinner}>{t.publicDemo.statusVerified}</DataRow>
              <DataRow label={t.publicDemo.coverageAmountDates}>{t.publicDemo.statusVerified}</DataRow>
              <DataRow label={t.publicDemo.coverageQuantities}>{t.publicDemo.statusVerifiedNotice}</DataRow>
              <DataRow label={t.publicDemo.coverageRelevance}>{t.publicDemo.statusStrongCompatible}</DataRow>
              <DataRow label={t.publicDemo.coverageNeeds}>{t.publicDemo.statusInferredVolumes}</DataRow>
              <DataRow label={t.publicDemo.coverageDocumentary}>{t.publicDemo.statusPartial}</DataRow>
            </DataList>
          </details>
        </div>
      </section>

      <section className={`${styles.section} ${styles.finalCta}`} aria-labelledby="final-cta-title">
        <div className={styles.finalCtaInner}>
          <h2 id="final-cta-title">{t.publicDemo.finalCtaTitle}</h2>
          <p>{t.publicDemo.finalCtaBody}</p>
          <p className={styles.noCard}>{t.publicDemo.finalCtaNoCard}</p>
          <div className={`${styles.actions} ${styles.finalActions}`}>
            <ButtonLink to="/signup" variant="primary" size="lg">
              {t.publicDemo.finalCtaPrimary}
            </ButtonLink>
            <ButtonLink to="/#comment" variant="secondary" size="lg">
              {t.publicDemo.finalCtaSecondary}
            </ButtonLink>
          </div>
        </div>
      </section>
    </div>
  )
}
