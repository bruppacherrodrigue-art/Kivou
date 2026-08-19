import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useI18n } from '../i18n'
import { Badge, Callout, Card, DataList, DataRow, SectionHeading, Skeleton } from '../components/Surfaces'
import { ButtonLink } from '../components/Button'
import { ArrowRightIcon, BuildingIcon, ExternalIcon, LockIcon } from '../assets/Icons'
import { NeedList } from '../signals/NeedList'
import { EvidencePanel } from '../signals/EvidenceGroup'
import { FeedbackControl } from '../feedback/FeedbackControl'
import { signals } from '../api/endpoints'
import { ApiError } from '../api/client'
import { describeError } from '../api/errorCopy'
import type { LockedDetail, SignalDetail as SignalDetailPayload, UnlockedDetail } from '../api/types'
import styles from './SignalDetail.module.css'

/* Le détail d'un signal.
 *
 * La séparation FAITS / ANALYSE est la crédibilité même de Kivou, et elle est
 * portée par la STRUCTURE, pas par une nuance de gris : deux sections nommées,
 * deux en-têtes, un liseré brass sur l'analyse. Un lecteur qui parcourt la page
 * doit voir où finit ce que la source publie et où commence ce que Kivou en
 * déduit.
 *
 * Rien n'est recalculé : `event.headline`, `event.why_now`, les libellés de
 * besoin et les motifs de fit viennent de l'API, déjà dans la langue du compte.
 */
export function SignalDetail() {
  const { signalKey = '' } = useParams()
  const { t } = useI18n()
  const [detail, setDetail] = useState<SignalDetailPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    signals
      .detail(signalKey)
      .then((result) => {
        if (active) setDetail(result)
      })
      .catch((caught) => {
        if (active) setError(caught)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [signalKey])

  if (loading) return <DetailSkeleton />

  if (error) {
    const notFound = error instanceof ApiError && error.status === 404
    const copy = describeError(error, t)
    return (
      <div className={styles.page}>
        <BackLink />
        <Callout tone="danger" title={notFound ? t.detail.notFoundTitle : copy.title} live>
          {notFound ? t.detail.notFoundBody : copy.body}
        </Callout>
      </div>
    )
  }

  if (!detail) return null

  return detail.locked ? <LockedDetailView detail={detail} /> : <UnlockedDetailView detail={detail} />
}

function BackLink() {
  const { t } = useI18n()
  return (
    <Link to="/app/signals" className={styles.back}>
      <ArrowRightIcon className={styles.backIcon} aria-hidden="true" />
      {t.detail.backToFeed}
    </Link>
  )
}

/* Le détail VERROUILLÉ.
 *
 * Il rend exactement les champs du teaser, et rien d'autre. Aucune tentative de
 * reconstituer l'entreprise gagnante depuis l'URL, un identifiant de source, un
 * cache navigateur ou une autre réponse : ces champs ne sont tout simplement
 * pas dans la charge utile.
 *
 * Aucun contrôle de retour n'apparaît ici — juger suppose d'avoir vu, et le
 * backend refuserait d'ailleurs l'avis en 403.
 */
function LockedDetailView({ detail }: { detail: LockedDetail }) {
  const { t, date } = useI18n()

  return (
    <div className={styles.page}>
      <BackLink />

      <header className={styles.header}>
        <Badge tone="muted" icon={<LockIcon />}>
          {t.locked.badge}
        </Badge>
        <h1 className={styles.title}>{detail.headline}</h1>
        <p className={styles.whyNow}>{detail.event.why_now}</p>
      </header>

      <Card padding="lg" className={styles.lockedCard}>
        <h2 className={styles.lockedTitle}>{t.locked.detailTitle}</h2>
        <p className={styles.lockedBody}>{t.locked.detailBody}</p>

        <DataList>
          {detail.event.date ? (
            <DataRow label={t.detail.dates} tabular>
              {date(detail.event.date)}
            </DataRow>
          ) : null}
          {detail.context.place_country ?? detail.context.country ? (
            <DataRow label={t.locked.country}>
              {detail.context.place_country ?? detail.context.country}
            </DataRow>
          ) : null}
          {detail.context.sector ? (
            <DataRow label={t.locked.sector}>{detail.context.sector}</DataRow>
          ) : null}
          {detail.context.contract_magnitude ? (
            <DataRow label={t.locked.magnitude} tabular>
              {t.magnitude[detail.context.contract_magnitude]}
              {detail.context.currency ? ` ${detail.context.currency.toUpperCase()}` : ''}
            </DataRow>
          ) : null}
        </DataList>

        <div className={styles.lockedAction}>
          <ButtonLink to="/app/billing" size="lg">
            {t.locked.cta}
          </ButtonLink>
        </div>
      </Card>
    </div>
  )
}

function UnlockedDetailView({ detail }: { detail: UnlockedDetail }) {
  const { t, date, amount } = useI18n()
  const { company, contract, event, analysis, evidence, source } = detail

  return (
    <div className={styles.page}>
      <BackLink />

      <header className={styles.header}>
        <div className={styles.companyRow}>
          <BuildingIcon className={styles.companyIcon} aria-hidden="true" />
          <span className={styles.companyName}>{company.name ?? t.common.notAvailable}</span>
          {company.country ? <Badge tone="neutral">{company.country}</Badge> : null}
        </div>

        <h1 className={styles.title}>{contract.title ?? t.common.notAvailable}</h1>

        {/* La phrase de fraîcheur et le « pourquoi maintenant » viennent de
            `recency.claim` et `feed.copy` : ils précèdent le détail
            documentaire, parce que c'est ce qui décide d'agir. */}
        <p className={styles.headline}>{event.headline}</p>
        <p className={styles.whyNow}>{event.why_now}</p>
        {/* Le complément sur la date d'attribution empêche de lire une
            publication récente comme une décision récente. */}
        <p className={styles.awardNote}>{event.award_date_note}</p>
      </header>

      <div className={styles.columns}>
        <div className={styles.mainColumn}>
          {/* ── FAITS ─────────────────────────────────────────────────── */}
          <section className={styles.factsSection} aria-labelledby="kivou-facts">
            <SectionHeading
              eyebrow={t.detail.factsTitle}
              title={t.detail.factsLead}
              id="kivou-facts"
              level={2}
            />

            <Card padding="lg">
              <DataList>
                <DataRow label={t.detail.company}>{company.name ?? t.common.notAvailable}</DataRow>
                {contract.buyer?.name ? (
                  <DataRow label={t.detail.buyer}>{contract.buyer.name}</DataRow>
                ) : null}
                {contract.lot ? <DataRow label={t.detail.lot}>{contract.lot}</DataRow> : null}
                {contract.reference ? (
                  <DataRow label={t.detail.reference} tabular>
                    {contract.reference}
                  </DataRow>
                ) : null}
                <DataRow label={t.detail.amount} tabular>
                  {amount(contract.amount?.value, contract.amount?.currency) ??
                    t.common.notAvailable}
                </DataRow>
                {contract.location ? (
                  <DataRow label={t.detail.location}>
                    {[
                      contract.location.locality,
                      contract.location.postal_code,
                      contract.location.country,
                    ]
                      .filter(Boolean)
                      .join(', ') || t.common.notAvailable}
                  </DataRow>
                ) : null}
                {contract.cpv ? (
                  <DataRow label={t.detail.cpv} tabular>
                    {contract.cpv}
                  </DataRow>
                ) : null}

                {/* Les trois dates sont affichées SÉPARÉMENT : confondre
                    attribution, notification et publication est précisément ce
                    que la politique de fraîcheur interdit. */}
                <DataRow label={t.detail.dateAward} tabular>
                  {date(contract.dates.award) ?? t.common.notAvailable}
                </DataRow>
                <DataRow label={t.detail.dateNotification} tabular>
                  {date(contract.dates.contract_notification) ?? t.common.notAvailable}
                </DataRow>
                <DataRow label={t.detail.datePublication} tabular>
                  {date(contract.dates.publication) ?? t.common.notAvailable}
                </DataRow>
              </DataList>

              {source.url ? (
                <p className={styles.sourceLine}>
                  <a
                    className={styles.sourceLink}
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t.detail.sourceOpen}
                    <ExternalIcon className={styles.linkIcon} />
                  </a>
                  {source.system ? (
                    <span className={styles.sourceMeta}>
                      {source.system}
                      {source.notice_id ? ` · ${source.notice_id}` : ''}
                    </span>
                  ) : null}
                </p>
              ) : null}
            </Card>
          </section>

          {/* ── ANALYSE ───────────────────────────────────────────────── */}
          <section className={styles.analysisSection} aria-labelledby="kivou-analysis">
            <SectionHeading
              eyebrow={t.detail.analysisTitle}
              title={t.detail.analysisLead}
              id="kivou-analysis"
              level={2}
            />

            <Card padding="lg" className={styles.analysisCard}>
              <h3 className={styles.blockTitle}>{t.detail.needsTitle}</h3>
              <NeedList
                needs={analysis.plausible_needs.items}
                note={analysis.plausible_needs.note}
                showReasoning
              />

              {analysis.contract_reading ? (
                <div className={styles.contractReading}>
                  <h3 className={styles.blockTitle}>{t.detail.contractReading}</h3>
                  <p className={styles.readingNote}>{analysis.contract_reading.note}</p>
                  {analysis.contract_reading.summary ? (
                    <p className={styles.readingText}>{analysis.contract_reading.summary}</p>
                  ) : null}
                  <DataList>
                    {analysis.contract_reading.contract_type ? (
                      <DataRow label={t.detail.contractType}>
                        {analysis.contract_reading.contract_type}
                      </DataRow>
                    ) : null}
                    {analysis.contract_reading.sector ? (
                      <DataRow label={t.detail.sector}>{analysis.contract_reading.sector}</DataRow>
                    ) : null}
                  </DataList>
                </div>
              ) : null}
            </Card>
          </section>

          {/* ── PREUVE ────────────────────────────────────────────────── */}
          <section className={styles.evidenceSection} aria-labelledby="kivou-evidence">
            <SectionHeading
              eyebrow={t.evidence.title}
              title={t.evidence.lead}
              id="kivou-evidence"
              level={2}
            />
            <EvidencePanel evidence={evidence} />
          </section>

          <FeedbackControl signalKey={detail.signal_id} initial={detail.interaction} />
        </div>

        <aside className={styles.sideColumn}>
          <Card padding="md" as="section" className={styles.fitCard}>
            <h2 className={styles.fitTitle}>{t.detail.fitTitle}</h2>
            <p className={styles.fitLabel}>{analysis.fit.label}</p>

            {analysis.fit.target_icp_label ? (
              <p className={styles.fitProfile}>
                <span className={styles.fitProfileLabel}>{t.detail.fitProfile}</span>
                {analysis.fit.target_icp_label}
              </p>
            ) : null}

            {analysis.fit.reasons.length > 0 ? (
              <>
                <p className={styles.fitReasonsLabel}>{t.detail.fitReasons}</p>
                <ul className={styles.fitReasons}>
                  {analysis.fit.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </Card>
        </aside>
      </div>
    </div>
  )
}

function DetailSkeleton() {
  const { t } = useI18n()
  return (
    <div className={styles.page}>
      {/* Même en chargement, la page porte un h1 : un document sans titre de
          niveau 1 n'offre aucun point d'entrée à la navigation par titres.
          Le titre réel n'est pas encore connu, donc l'état l'est. */}
      <h1 className="kivou-visually-hidden">{t.common.loading}</h1>
      <div aria-hidden="true">
      <Skeleton width="10rem" height="1rem" />
      <div className={styles.header}>
        <Skeleton width="14rem" height="1rem" />
        <Skeleton width="80%" height="2.25rem" />
        <Skeleton width="60%" height="1rem" />
      </div>
      <Card padding="lg">
        <div className={styles.skeletonStack}>
          {[0, 1, 2, 3, 4].map((index) => (
            <Skeleton key={index} width={`${90 - index * 8}%`} height="1rem" />
          ))}
        </div>
      </Card>
      </div>
    </div>
  )
}
