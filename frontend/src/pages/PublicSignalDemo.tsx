import { publicDemoSignal } from '../content/publicDemoSignal'
import { ButtonLink } from '../components/Button'
import { Badge, Callout, Card, DataList, DataRow, SectionHeading } from '../components/Surfaces'
import { useI18n } from '../i18n'
import styles from './PublicSignalDemo.module.css'

/* La démonstration publique d'un signal complet.
 *
 * Elle suit exactement l'ordre du produit
 * ───────────────────────────────────────
 *   fait public → exigence documentaire → analyse → timing → fit → preuve
 *
 * L'ordre n'est pas décoratif : il interdit de lire une inférence avant le
 * fait qui la fonde. C'est la même grammaire que la fiche authentifiée, sans
 * un gramme de sa logique — ni session, ni facturation, ni retour client, ni
 * appel réseau. Cette page est lisible hors connexion.
 *
 * La section « exigence documentaire » reste, et elle est VIDE
 * ───────────────────────────────────────────────────────────
 * Ce signal n'a aucune exigence d'exécution validée. Supprimer la section
 * aurait laissé croire que Kivou en produit toujours une ; la remplir aurait
 * demandé d'inventer un passage. Elle affiche donc l'état réel : mode
 * `metadata_fallback`, confiance réduite, et la raison de cette réduction.
 *
 * La formulation porte sur les DONNÉES KIVOU, jamais sur l'existence des
 * pièces du marché : nous ne savons pas si un cahier des charges existe pour
 * cette attribution, seulement qu'aucun n'alimente ce signal.
 */
export function PublicSignalDemo() {
  const { t, locale, amount, date } = useI18n()
  const s = publicDemoSignal
  const value = amount(s.contract.amount, s.contract.currency)

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Badge tone="brand">{t.publicDemo.badge}</Badge>
        <h1 className={styles.title}>{t.publicDemo.pageTitle}</h1>
        <p className={styles.lead}>{t.publicDemo.pageLead}</p>
        {/* `last_verified_at` est visible, pas caché dans un attribut : une
            donnée de démonstration sans date de vérification vieillit sans
            que personne ne s'en aperçoive. */}
        <p className={styles.verified}>
          {t.publicDemo.verifiedOn.replace('{date}', date(s.lastVerifiedAt) ?? s.lastVerifiedAt)}
        </p>
      </header>

      {/* ── 1. FAIT PUBLIC ────────────────────────────────────────────── */}
      <Card padding="lg" as="section" className={styles.factsCard}>
        <SectionHeading
          eyebrow={t.publicDemo.factsTitle}
          title={s.winner.legalName}
          lead={t.publicDemo.factsLead}
          id="kivou-public-facts"
        />
        <p className={styles.object}>{s.contract.title}</p>

        <DataList>
          <DataRow label={t.publicDemo.buyer}>{s.buyer.legalName}</DataRow>
          <DataRow label={t.publicDemo.amountLabel} tabular>
            {value}
          </DataRow>
          <DataRow label={t.publicDemo.place}>
            {s.contract.postalCode} {s.contract.locality} · {s.contract.country}
          </DataRow>
          <DataRow label={t.publicDemo.reference} tabular>
            {s.contract.reference}
          </DataRow>
          <DataRow label={t.publicDemo.cpv} tabular>
            {s.contract.cpv}
          </DataRow>
          <DataRow label={t.publicDemo.identifier} tabular>
            {s.winner.identifier.value}
          </DataRow>
        </DataList>

        <div className={styles.quantities}>
          <h3 className={styles.blockTitle}>{t.publicDemo.quantitiesTitle}</h3>
          <ul className={styles.quantityList}>
            {s.contract.publishedQuantities.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          {/* Le garde-fou qui compte : ces quantités viennent du descriptif de
              l'AVIS, pas d'un cahier des charges. Les confondre transformerait
              une métadonnée en preuve documentaire. */}
          <p className={styles.note}>{t.publicDemo.quantitiesNote}</p>
        </div>
      </Card>

      {/* ── 2. EXIGENCE DOCUMENTAIRE — absente, et dit comme tel ──────── */}
      <Card padding="lg" as="section" className={styles.documentaryCard}>
        <SectionHeading
          eyebrow={t.publicDemo.documentaryTitle}
          title={t.publicDemo.documentaryNone}
          id="kivou-public-documentary"
        />
        <DataList>
          <DataRow label={t.publicDemo.documentaryModeLabel}>
            {t.publicDemo.documentaryMode}
          </DataRow>
          <DataRow label={t.publicDemo.documentaryConfidenceLabel}>
            <Badge tone="warm">{t.publicDemo.documentaryConfidence}</Badge>
          </DataRow>
        </DataList>
        <p className={styles.note}>{t.publicDemo.documentaryConfidenceReason}</p>
      </Card>

      {/* ── 3. ANALYSE KIVOU ─────────────────────────────────────────── */}
      <Card padding="lg" as="section" className={styles.analysisCard}>
        <SectionHeading
          eyebrow={t.publicDemo.analysisTitle}
          title={s.need.statement[locale]}
          lead={t.publicDemo.analysisLead}
          id="kivou-public-analysis"
        />
        <DataList>
          <DataRow label={t.publicDemo.reasoningLabel}>{s.need.reasoning[locale]}</DataRow>
          <DataRow label={t.publicDemo.needTimingLabel}>
            {t.publicDemo.needTimingNearTerm}
          </DataRow>
          <DataRow label={t.publicDemo.externalisabilityLabel}>
            {t.publicDemo.externalisabilityPlausible}
          </DataRow>
        </DataList>
      </Card>

      {/* ── 4. TIMING — dates absolues uniquement ────────────────────── */}
      <Card padding="lg" as="section" className={styles.timingCard}>
        <SectionHeading
          eyebrow={t.publicDemo.timingTitle}
          title={t.publicDemo.timingLead}
          id="kivou-public-timing"
        />
        <DataList>
          <DataRow label={t.publicDemo.awardDate} tabular>
            {date(s.timing.awardDate)}
          </DataRow>
          <DataRow label={t.publicDemo.signatureDate} tabular>
            {date(s.timing.signatureDate)}
          </DataRow>
          <DataRow label={t.publicDemo.startDate} tabular>
            {date(s.timing.startDate)}
          </DataRow>
          <DataRow label={t.publicDemo.endDate} tabular>
            {date(s.timing.endDate)}
          </DataRow>
          <DataRow label={t.publicDemo.publishedAt} tabular>
            {date(s.timing.publishedAt)}
          </DataRow>
        </DataList>
        <p className={styles.note}>{t.publicDemo.timingNote}</p>
      </Card>

      {/* ── 5. FIT — explicitement illustratif ───────────────────────── */}
      <Callout tone="info" title={t.publicDemo.fitTitle}>
        <p className={styles.fitLead}>{t.publicDemo.fitLead}</p>
        <p>{t.publicDemo.fitBody}</p>
      </Callout>

      {/* ── 6. PREUVE ────────────────────────────────────────────────── */}
      <Card padding="lg" as="section" className={styles.evidenceCard}>
        <SectionHeading
          eyebrow={t.publicDemo.evidenceTitle}
          title={t.publicDemo.evidenceLead}
          id="kivou-public-evidence"
        />
        {/* Libellés HUMAINS en surface. Trois champs seulement portent un
            renvoi de provenance : l'écran doit donc parler de champs
            « sélectionnés », jamais de « chaque fait ». */}
        <p className={styles.note}>{t.publicDemo.evidenceScope}</p>
        <DataList>
          {s.evidence.map((piece) => (
            <DataRow key={piece.path} label={t.publicDemo[piece.labelKey]}>
              <span className="kivou-tabular">{piece.rawValue}</span>
            </DataRow>
          ))}
        </DataList>

        {/* Les chemins techniques sont repliés : ils servent à l'audit, pas à
            la lecture. `details` natif — accessible au clavier sans code. */}
        <details className={styles.technical}>
          <summary className={styles.technicalSummary}>{t.publicDemo.evidenceTechnical}</summary>
          <DataList>
            {s.evidence.map((piece) => (
              <DataRow
                key={piece.path}
                // Un chemin n'est qualifié de XML que s'il en est un. `value` et
                // `lot.identifier` sont des champs d'acquisition, pas des
                // chemins dans le document TED.
                label={
                  piece.pathKind === 'xml'
                    ? t.publicDemo.evidencePathXml
                    : t.publicDemo.evidencePathField
                }
              >
                <span className={styles.path}>{piece.path}</span>
              </DataRow>
            ))}
          </DataList>
        </details>
        {/* `noopener noreferrer` : sans lui, la page ouverte garde une
            référence sur `window.opener` et peut réécrire notre onglet. */}
        <a
          className={styles.sourceLink}
          href={s.sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          {t.publicDemo.openSource}
          <span aria-hidden="true"> ↗</span>
        </a>
        <p className={styles.note}>{t.publicDemo.openSourceHint}</p>
      </Card>

      {/* ── ACTION ───────────────────────────────────────────────────── */}
      <Card padding="lg" as="section" className={styles.ctaCard}>
        <h2 className={styles.ctaTitle}>{t.publicDemo.ctaTitle}</h2>
        <p className={styles.ctaBody}>{t.publicDemo.ctaBody}</p>
        <ButtonLink to="/signup" variant="primary" size="lg">
          {t.publicDemo.ctaButton}
        </ButtonLink>
      </Card>
    </div>
  )
}
