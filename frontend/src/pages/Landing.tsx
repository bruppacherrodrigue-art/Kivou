import { useEffect, useState } from 'react'
import { useI18n } from '../i18n'
import { ButtonLink } from '../components/Button'
import { Card, SectionHeading } from '../components/Surfaces'
import { ArchitecturalHero } from '../assets/Illustrations'
import { PublicSignalPreview } from '../components/PublicSignalPreview'
import {
  ArrowRightIcon,
  CheckIcon,
  ClockIcon,
  DocumentIcon,
  NeedIcon,
  ShieldIcon,
  TargetIcon,
} from '../assets/Icons'
import { PlanGrid } from '../billing/PlanGrid'
import { billing } from '../api/endpoints'
import type { PlanCatalogue } from '../api/types'
import styles from './Landing.module.css'

/* La page publique.
 *
 * Elle dit ce que le MVP fait RÉELLEMENT : un événement public, ce qu'il
 * implique probablement, et la preuve qui permet d'en juger. Elle ne dit nulle
 * part que Kivou sait ce qu'une entreprise va acheter.
 *
 * Ce qui n'y figure pas, et pourquoi :
 * — aucun logo de client. Ceux de la référence 02 sont fictifs, et le pack
 *   interdit de les publier sans autorisation ni source réelle. Le bandeau de
 *   confiance nomme donc les SOURCES publiques, qui sont vérifiables ;
 * — aucun prix écrit en dur. La grille vient de `GET /billing/plans` ;
 * — l'offre Founding, privée, n'apparaît pas : le catalogue public ne la
 *   contient pas, et rien ici ne la reconstitue.
 */
export function Landing() {
  const { t } = useI18n()
  const [catalogue, setCatalogue] = useState<PlanCatalogue | null>(null)

  useEffect(() => {
    let active = true
    billing
      .plans()
      .then((result) => {
        if (active) setCatalogue(result)
      })
      .catch(() => {
        // Le catalogue indisponible ne casse pas la page : la section tarifaire
        // s'efface, le reste de la promesse tient debout.
      })
    return () => {
      active = false
    }
  }, [])

  const chain = [
    { key: 'fact', Icon: DocumentIcon, title: t.landing.chain.factTitle, body: t.landing.chain.factBody },
    {
      key: 'requirement',
      Icon: ShieldIcon,
      title: t.landing.chain.requirementTitle,
      body: t.landing.chain.requirementBody,
    },
    { key: 'need', Icon: NeedIcon, title: t.landing.chain.needTitle, body: t.landing.chain.needBody },
    { key: 'timing', Icon: ClockIcon, title: t.landing.chain.timingTitle, body: t.landing.chain.timingBody },
    {
      key: 'action',
      Icon: ArrowRightIcon,
      title: t.landing.chain.actionTitle,
      body: t.landing.chain.actionBody,
    },
  ]

  const proofs = [
    { Icon: ShieldIcon, title: t.landing.proofs.publicTitle, body: t.landing.proofs.publicBody },
    { Icon: DocumentIcon, title: t.landing.proofs.documentTitle, body: t.landing.proofs.documentBody },
    { Icon: TargetIcon, title: t.landing.proofs.actionableTitle, body: t.landing.proofs.actionableBody },
  ]

  return (
    <>
      <section className={styles.hero}>
        <div className={styles.heroInner}>
          <div className={styles.heroText}>
            <h1 className={styles.h1}>{t.brand.promise}</h1>
            <p className={styles.heroLead}>{t.landing.heroLead}</p>
            <div className={styles.heroActions}>
              <ButtonLink to="/signup" variant="primary" size="lg" icon={<ArrowRightIcon />}>
                {t.landing.heroPrimary}
              </ButtonLink>
              <ButtonLink to="/exemple-de-signal" variant="secondary" size="lg">
                {t.landing.heroSecondary}
              </ButtonLink>
            </div>

            <ul className={styles.proofs}>
              {proofs.map(({ Icon, title, body }) => (
                <li key={title} className={styles.proof}>
                  <span className={styles.proofIcon} aria-hidden="true">
                    <Icon />
                  </span>
                  <span>
                    <span className={styles.proofTitle}>{title}</span>
                    <span className={styles.proofBody}>{body}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {/* La colonne droite montrait la direction artistique ; elle montre
              désormais ce que Kivou produit. L'illustration reste comme accent
              de matière, derrière la carte, et non à sa place. */}
          <div className={styles.heroMaterial}>
            <ArchitecturalHero className={styles.heroIllustration} aria-hidden="true" />
            <div className={styles.heroSignal}>
              <PublicSignalPreview />
            </div>
          </div>
        </div>
      </section>

      <section className={styles.section} id="comment">
        <div className={styles.sectionInner}>
          <SectionHeading
            eyebrow={t.landing.chainTitle}
            title={t.landing.chainLead}
            level={2}
          />
          {/* La numérotation encode une vraie séquence : chaque étape consomme
              la sortie de la précédente. Ce n'est pas un ornement. */}
          <ol className={styles.chain}>
            {chain.map(({ key, Icon, title, body }, index) => (
              <li key={key} className={styles.chainStep}>
                <Card padding="md" className={styles.chainCard}>
                  <span className={styles.chainNumber} aria-hidden="true">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span className={styles.chainIcon} aria-hidden="true">
                    <Icon />
                  </span>
                  <h3 className={styles.chainTitle}>{title}</h3>
                  <p className={styles.chainBody}>{body}</p>
                </Card>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className={`${styles.section} ${styles.sectionSubtle}`}>
        <div className={styles.sectionInner}>
          <SectionHeading title={t.landing.honestyTitle} />
          <div className={styles.honesty}>
            <Card padding="lg" className={styles.honestyCard}>
              <h3 className={styles.honestyTitle}>{t.landing.honestyAffirms}</h3>
              <ul className={styles.honestyList}>
                {t.landing.honestyAffirmsItems.map((item) => (
                  <li key={item}>
                    <CheckIcon className={styles.honestyIcon} aria-hidden="true" />
                    {item}
                  </li>
                ))}
              </ul>
            </Card>

            {/* Le second bloc porte un liseré brass : il énonce des HYPOTHÈSES,
                et rien ne doit le faire lire comme le premier. */}
            <Card padding="lg" className={`${styles.honestyCard} ${styles.honestyQualified}`}>
              <h3 className={styles.honestyTitle}>{t.landing.honestyQualifies}</h3>
              <ul className={styles.honestyList}>
                {t.landing.honestyQualifiesItems.map((item) => (
                  <li key={item}>
                    <NeedIcon className={styles.honestyIcon} aria-hidden="true" />
                    {item}
                  </li>
                ))}
              </ul>
            </Card>
          </div>
          <p className={styles.honestyNote}>{t.landing.honestyNote}</p>
        </div>
      </section>

      {catalogue ? (
        <section className={styles.section} id="tarifs">
          <div className={styles.sectionInner}>
            <SectionHeading title={t.landing.pricingTitle} lead={t.landing.pricingLead} />
            <PlanGrid catalogue={catalogue} variant="public" />
          </div>
        </section>
      ) : null}

      <section className={`${styles.section} ${styles.sectionCta}`}>
        <div className={styles.ctaInner}>
          <h2 className={styles.ctaTitle}>{t.landing.ctaTitle}</h2>
          <p className={styles.ctaBody}>{t.landing.ctaBody}</p>
          <div className={styles.heroActions}>
            <ButtonLink to="/signup" variant="primary" size="lg" icon={<ArrowRightIcon />}>
              {t.nav.signup}
            </ButtonLink>
            <ButtonLink to="/login" variant="secondary" size="lg">
              {t.nav.login}
            </ButtonLink>
          </div>
        </div>
      </section>
    </>
  )
}
