import { ButtonExternalLink, ButtonLink } from '../components/Button'
import { Badge, Card, DataList, DataRow, SectionHeading } from '../components/Surfaces'
import {
  publicDemoSignal,
  type PublicDemoEvidence,
  type PublicDemoSignal,
} from '../content/publicDemoSignal'
import { interpolate, useI18n } from '../i18n'
import styles from './PublicSignalDemo.module.css'

interface PublicSignalDemoProps {
  /** Permet de vérifier qu'une autre projection publique se rend sans modifier
   * les dictionnaires. La route publique utilise toujours la fixture validée. */
  readonly signal?: PublicDemoSignal
}

interface PublishedQuantity {
  readonly sourceLabel: string
  readonly value: string
}

const EVIDENCE_ORDER: readonly PublicDemoEvidence['labelKey'][] = [
  'evidenceCpv',
  'evidenceAmount',
  'evidenceLot',
]

function parsePublishedQuantity(line: string): PublishedQuantity {
  const separator = line.lastIndexOf(' : ')
  return {
    sourceLabel: separator >= 0 ? line.slice(0, separator) : line,
    value: separator >= 0 ? line.slice(separator + 3) : '',
  }
}

function compactAmount(value: string, currency: string, locale: 'fr' | 'en'): string {
  const numeric = Number(value)
  if (Number.isNaN(numeric)) return `${value} ${currency}`
  return new Intl.NumberFormat(locale === 'fr' ? 'fr-FR' : 'en-GB', {
    style: 'currency',
    currency: currency.toUpperCase(),
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(numeric)
}

function regionName(code: string, locale: 'fr' | 'en'): string {
  return new Intl.DisplayNames([locale], { type: 'region' }).of(code) ?? code
}

/** Démonstration publique statique et sans donnée de compte.
 *
 * Les dictionnaires portent uniquement la structure éditoriale. Entreprise,
 * montant, lieu, dates, quantités, coordonnées et preuves sont interpolés
 * depuis la projection publique reçue par le composant. */
export function PublicSignalDemo({ signal = publicDemoSignal }: PublicSignalDemoProps) {
  const { t, locale, date } = useI18n()
  const s = signal
  const roundedAmount = compactAmount(s.contract.amount, s.contract.currency, locale)
  const winnerCountry = regionName(s.winner.country, locale)
  const contractCountry = regionName(s.contract.country, locale)
  const quantities = s.contract.publishedQuantities.map(parsePublishedQuantity)
  const quantityLabels = [
    t.publicDemo.quantityWoodDoors,
    t.publicDemo.quantitySteelDoors,
    t.publicDemo.quantitySkirting,
    t.publicDemo.quantityWallCladding,
    t.publicDemo.quantityGlazing,
    t.publicDemo.quantityKitchenettes,
  ]

  const factValues = {
    company: s.winner.legalName,
    amount: roundedAmount,
    location: s.contract.locality,
    place: `${s.contract.postalCode} ${s.contract.locality}`,
    country: contractCountry,
    startDate: date(s.timing.startDate) ?? s.timing.startDate,
    woodDoors: quantities[0]?.value ?? '',
    steelDoors: quantities[1]?.value ?? '',
    skirting: quantities[2]?.value ?? '',
    wallCladding: quantities[3]?.value ?? '',
    glazing: quantities[4]?.value ?? '',
    kitchenettes: quantities[5]?.value ?? '',
  }
  const copy = (template: string) => interpolate(template, factValues)

  const opportunities = [
    { title: t.publicDemo.opportunityDoorsTitle, body: copy(t.publicDemo.opportunityDoorsBody) },
    { title: t.publicDemo.opportunityWoodTitle, body: copy(t.publicDemo.opportunityWoodBody) },
    { title: t.publicDemo.opportunityGlazingTitle, body: copy(t.publicDemo.opportunityGlazingBody) },
    { title: t.publicDemo.opportunityKitchenTitle, body: copy(t.publicDemo.opportunityKitchenBody) },
  ]

  const matchingReasons = [
    t.publicDemo.matchingReasonOne,
    t.publicDemo.matchingReasonTwo,
    copy(t.publicDemo.matchingReasonThree),
    t.publicDemo.matchingReasonFour,
    t.publicDemo.matchingReasonFive,
    t.publicDemo.matchingReasonSix,
  ]

  const timeline = [
    { date: date(s.timing.awardDate), label: t.publicDemo.timelineAwarded },
    { date: date(s.timing.signatureDate), label: t.publicDemo.timelineSigned },
    { date: date(s.timing.publishedAt), label: t.publicDemo.timelinePublished },
    { date: date(s.timing.startDate), label: t.publicDemo.timelineStart },
    { date: date(s.timing.endDate), label: t.publicDemo.timelineEnd },
  ]

  const evidenceByLabel = new Map(s.evidence.map((piece) => [piece.labelKey, piece]))
  const selectedEvidence = EVIDENCE_ORDER.flatMap((labelKey) => {
    const piece = evidenceByLabel.get(labelKey)
    return piece ? [piece] : []
  })
  const actionItems = [
    t.publicDemo.actionReviewMarket,
    t.publicDemo.actionCheckFit,
    t.publicDemo.actionOpenNotice,
    t.publicDemo.actionCreateAccount,
  ]

  return (
    <div className={styles.page}>
      <section className={styles.hero} aria-labelledby="public-signal-title">
        <div className={styles.heroInner}>
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>{t.publicDemo.heroEyebrow}</p>
            <h1 className={styles.heroTitle} id="public-signal-title">
              {copy(t.publicDemo.heroTitle)}
            </h1>
            <p className={styles.heroSubtitle}>{copy(t.publicDemo.heroSubtitle)}</p>
            <p className={styles.heroTiming}>{copy(t.publicDemo.heroTiming)}</p>

            <div className={styles.badges} aria-label={t.publicDemo.contractSnapshot}>
              <Badge tone="positive">{t.publicDemo.heroBadgeVerified}</Badge>
              <Badge tone="brand">{t.publicDemo.heroBadgeAwardDate}</Badge>
              <Badge tone="neutral">{t.publicDemo.heroBadgeSchedule}</Badge>
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
                {s.contract.postalCode} {s.contract.locality} · {contractCountry}
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
            <p>{copy(t.publicDemo.overviewBody)}</p>
            <div className={styles.needAnalysis}>
              <p className={styles.needLabel}>{t.publicDemo.needLabel}</p>
              <p>{s.need.statement[locale]}</p>
              <p>{s.need.reasoning[locale]}</p>
            </div>
            <p className={styles.overviewHighlight}>{t.publicDemo.overviewHighlight}</p>
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionSubtle}`} aria-labelledby="volumes-title">
        <div className={styles.sectionInner}>
          <SectionHeading title={t.publicDemo.volumesTitle} lead={t.publicDemo.volumesLead} id="volumes-title" />
          <ul className={styles.volumeGrid}>
            {quantities.map((quantity, index) => (
              <li className={styles.volumeCard} key={`${quantity.sourceLabel}-${quantity.value}`}>
                <span className={styles.volumeValue}>{quantity.value}</span>
                <span className={styles.volumeLabel}>{quantityLabels[index]}</span>
                <span className={styles.volumeSource}>{quantity.sourceLabel}</span>
              </li>
            ))}
          </ul>
          <p className={styles.sectionNote}>{t.publicDemo.quantitiesNote}</p>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="opportunities-title">
        <div className={styles.sectionInner}>
          <SectionHeading title={t.publicDemo.opportunitiesTitle} lead={t.publicDemo.opportunitiesLead} id="opportunities-title" />
          <div className={styles.opportunityGrid}>
            {opportunities.map((opportunity) => (
              <Card key={opportunity.title} padding="lg" as="article" className={styles.opportunityCard}>
                <Badge tone="brand">{t.publicDemo.plausibleAngle}</Badge>
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
            <h2 className={styles.matchingTitle} id="matching-title">{t.publicDemo.matchingTitle}</h2>
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
              <li key={item.label}>
                <span className={styles.timelineMarker} aria-hidden="true" />
                <span className={styles.timelineDate}>{item.date}</span>
                <span className={styles.timelineLabel}>{item.label}</span>
              </li>
            ))}
          </ol>
          <div className={styles.timingExplanation}>
            <h3>{t.publicDemo.timingWhyTitle}</h3>
            <p>{copy(t.publicDemo.timingBody)}</p>
          </div>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionSubtle}`} aria-labelledby="company-title">
        <div className={styles.sectionInner}>
          <SectionHeading title={t.publicDemo.companyTitle} lead={t.publicDemo.companyLead} id="company-title" />
          <div className={styles.companyGrid}>
            <Card padding="lg" as="article" className={styles.companyCard}>
              <h3 className={styles.cardTitle}>{t.publicDemo.companyTedFactsTitle}</h3>
              <DataList>
                <DataRow label={t.publicDemo.companyLegalName}>{s.winner.legalName}</DataRow>
                {s.winner.address ? <DataRow label={t.publicDemo.companyOfficialAddress}>{s.winner.address}</DataRow> : null}
                <DataRow label={t.publicDemo.companyCountry}>{winnerCountry}</DataRow>
                <DataRow label={t.publicDemo.companyIdentifier}>{s.winner.identifier.value}</DataRow>
                <DataRow label={t.publicDemo.companyContract}>{s.contract.title}</DataRow>
                <DataRow label={t.publicDemo.companyBuyer}>{s.buyer.legalName}</DataRow>
              </DataList>
              <ButtonExternalLink href={s.sourceUrl} variant="secondary">
                {t.publicDemo.companyTedSource}
                <span className="kivou-visually-hidden"> {t.publicDemo.externalNewTab}</span>
              </ButtonExternalLink>
            </Card>

            <Card padding="lg" as="article" className={styles.companyCard}>
              <h3 className={styles.cardTitle}>{t.publicDemo.companyContactTitle}</h3>
              <p className={styles.companyIntro}>{t.publicDemo.companyContactIntro}</p>
              <DataList>
                {s.winner.website ? (
                  <DataRow label={t.publicDemo.companyWebsite}>
                    <a className={styles.externalTextLink} href={s.winner.website} target="_blank" rel="noopener noreferrer">
                      {t.publicDemo.companyWebsiteLink}
                      <span className="kivou-visually-hidden"> {t.publicDemo.externalNewTab}</span>
                    </a>
                  </DataRow>
                ) : null}
                {s.winner.phone ? <DataRow label={t.publicDemo.companyPhone}>{s.winner.phone}</DataRow> : null}
                {s.winner.contactVerifiedAt ? (
                  <DataRow label={t.publicDemo.companyContactVerified}>{date(s.winner.contactVerifiedAt)}</DataRow>
                ) : null}
                {s.winner.contactVerificationSource ? (
                  <DataRow label={t.publicDemo.companyContactSource}>
                    <a className={styles.externalTextLink} href={s.winner.contactVerificationSource} target="_blank" rel="noopener noreferrer">
                      {t.publicDemo.companyContactSourceLink}
                      <span className="kivou-visually-hidden"> {t.publicDemo.externalNewTab}</span>
                    </a>
                  </DataRow>
                ) : null}
              </DataList>
            </Card>
          </div>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="action-title">
        <div className={`${styles.sectionInner} ${styles.actionGrid}`}>
          <div className={styles.actionCopy}>
            <SectionHeading eyebrow={t.publicDemo.actionEyebrow} title={t.publicDemo.actionTitle} id="action-title" />
            <p>{t.publicDemo.actionBody}</p>
            <div className={styles.actions}>
              <ButtonLink to="/signup" variant="primary" size="lg">{t.publicDemo.actionPrimary}</ButtonLink>
              <ButtonExternalLink href={s.sourceUrl} variant="secondary" size="lg">
                {t.publicDemo.actionSecondary}
                <span className="kivou-visually-hidden"> {t.publicDemo.externalNewTab}</span>
              </ButtonExternalLink>
            </div>
          </div>
          <Card padding="lg" className={styles.actionCard}>
            <h3>{t.publicDemo.actionListTitle}</h3>
            <ul className={styles.actionList}>
              {actionItems.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </Card>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionSubtle}`} aria-labelledby="evidence-title">
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
              {selectedEvidence.map((piece) => (
                <DataRow key={piece.labelKey} label={t.publicDemo[piece.labelKey]} tabular>{piece.rawValue}</DataRow>
              ))}
              <DataRow label={t.publicDemo.evidenceReference} tabular>{s.contract.reference}</DataRow>
              <DataRow label={t.publicDemo.evidenceIdentifier} tabular>{s.winner.identifier.value}</DataRow>
              <DataRow label={t.publicDemo.evidenceSignature} tabular>{date(s.timing.signatureDate)}</DataRow>
            </DataList>
            <details className={styles.technical}>
              <summary className={styles.technicalSummary}>{t.publicDemo.evidenceTechnical}</summary>
              <DataList>
                {selectedEvidence.map((piece) => (
                  <DataRow key={piece.labelKey} label={t.publicDemo[piece.labelKey]}>
                    <span className={styles.provenanceValue}>{piece.rawValue}</span>
                    <span className={styles.provenanceKind}>
                      {piece.pathKind === 'xml' ? t.publicDemo.evidencePathXml : t.publicDemo.evidencePathField}
                    </span>
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
              <DataRow label={t.publicDemo.coverageWinner}>{t.publicDemo.statusIdentified}</DataRow>
              <DataRow label={t.publicDemo.coverageAmountDates}>{t.publicDemo.statusPublished}</DataRow>
              <DataRow label={t.publicDemo.coverageQuantities}>{t.publicDemo.statusPublishedDescription}</DataRow>
              <DataRow label={t.publicDemo.coverageNeeds}>{t.publicDemo.statusPlausible}</DataRow>
              <DataRow label={t.publicDemo.coverageDocumentary}>{t.publicDemo.statusLimited}</DataRow>
              <DataRow label={t.publicDemo.coverageMode}>{t.publicDemo.statusMetadata}</DataRow>
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
            <ButtonLink to="/signup" variant="primary" size="lg">{t.publicDemo.finalCtaPrimary}</ButtonLink>
          </div>
        </div>
      </section>
    </div>
  )
}
