import { useEffect, useState } from 'react'
import { useI18n } from '../i18n'
import { ButtonLink } from '../components/Button'
import { Card, SectionHeading } from '../components/Surfaces'
import { HeroSignalCarousel } from '../components/HeroSignalCarousel'
import {
  ArrowRightIcon,
  CheckIcon,
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
        // conserve son ancre et affiche un état explicite sans inventer de prix.
      })
    return () => {
      active = false
    }
  }, [])

  const how = t.landing.how
  return (
    <>
      <section className={styles.hero}>
        <div className={styles.heroInner}>
          <div className={styles.heroText}>
            <p className={styles.heroEyebrow}>{t.landing.heroEyebrow}</p>
            <h1 className={styles.h1}>{t.landing.heroTitle}</h1>
            <p className={styles.heroLead}>{t.landing.heroLead}</p>
            <p className={styles.heroSecondaryLead}>{t.landing.heroSecondaryLead}</p>
            <div className={styles.heroActions}>
              <ButtonLink to="/signup" variant="primary" size="lg" icon={<ArrowRightIcon />}>
                {t.landing.heroPrimary}
              </ButtonLink>
              <ButtonLink to="/exemple-de-signal" variant="secondary" size="lg">
                {t.landing.heroSecondary}
              </ButtonLink>
            </div>
            <p className={styles.heroTrust}>
              <ShieldIcon aria-hidden="true" />
              {t.landing.heroTrust}
            </p>
          </div>

          <div className={styles.heroCarousel}>
            <HeroSignalCarousel />
          </div>
        </div>
      </section>

      <section className={styles.section} id="comment" tabIndex={-1}>
        <div className={`${styles.sectionInner} ${styles.howIntro}`}>
          <SectionHeading
            eyebrow={how.introEyebrow}
            title={how.introTitle}
            lead={
              <>
                {how.introBodyOne}
              </>
            }
            level={2}
          />
          <p className={styles.howHighlight}>{how.introHighlight}</p>

          <div className={styles.profileBlock}>
            <div className={styles.profileCopy}>
              <p className={styles.eyebrow}>{how.profileEyebrow}</p>
              <h3 className={styles.blockHeading}>{how.profileTitle}</h3>
              <p className={styles.blockLead}>{how.profileBody}</p>
            </div>
            <div className={styles.profileMap} aria-label={how.profileOutput}>
              <div className={styles.profileCards}>
                {how.profileCards.map((card) => (
                  <Card padding="md" className={styles.profileCard} key={card.title}>
                    <h4>{card.title}</h4>
                    <p>{card.body}</p>
                  </Card>
                ))}
              </div>
              <div className={styles.profileOutput}>
                <TargetIcon aria-hidden="true" />
                <span>{how.profileOutput}</span>
              </div>
            </div>
          </div>

          <section className={styles.processBlock} aria-labelledby="how-process-title">
            <h3 className={styles.blockHeading} id="how-process-title">
              {how.processTitle}
            </h3>
            <ol className={styles.processList} aria-label={how.processTitle}>
              {how.processSteps.map((step, index) => (
                <li
                  key={step.title}
                  className={`${styles.processStep} ${
                    index === how.processSteps.length - 1 ? styles.finalStep : ''
                  }`}
                >
                  <span className={styles.processNumber}>{String(index + 1).padStart(2, '0')}</span>
                  <h4>{step.title}</h4>
                  <p>{step.body}</p>
                </li>
              ))}
            </ol>
          </section>

          <section className={styles.dashboardBlock} aria-labelledby="how-dashboard-title">
            <div className={styles.dashboardCopy}>
              <SectionHeading
                eyebrow={how.dashboardEyebrow}
                title={how.dashboardTitle}
                lead={how.dashboardBody}
                id="how-dashboard-title"
                level={3}
              />
            </div>

            <ul className={styles.dashboardMarkers} aria-label={how.dashboardEyebrow}>
              {how.dashboardMarkers.map((marker) => (
                <li key={marker}>
                  <CheckIcon aria-hidden="true" />
                  {marker}
                </li>
              ))}
            </ul>

            <div className={styles.howActions}>
              <ButtonLink to="/exemple-de-signal" variant="primary" size="lg">
                {how.dashboardPrimary}
              </ButtonLink>
              <ButtonLink to="/signup" variant="secondary" size="lg">
                {how.dashboardSecondary}
              </ButtonLink>
            </div>
          </section>

        </div>
      </section>

      {/* La section existe TOUJOURS, même sans catalogue.
       *
       * Elle était rendue conditionnellement : `/#tarifs` devenait alors un
       * lien mort dès que la facturation était indisponible, et le visiteur
       * cliquait dans le vide sans rien comprendre. La cible est donc stable,
       * et c'est son CONTENU qui varie. `tabIndex={-1}` la rend focusable par
       * programme, pour que l'ancre déplace réellement le focus. */}
      <section className={`${styles.section} ${styles.pricingSection}`} id="tarifs" tabIndex={-1}>
        <div className={`${styles.sectionInner} ${styles.pricingInner}`}>
          <SectionHeading
            eyebrow={t.landing.pricingEyebrow}
            title={t.landing.pricingTitle}
            lead={t.landing.pricingLead}
          />
          {catalogue ? (
            <PlanGrid catalogue={catalogue} variant="public" />
          ) : (
            <p className={styles.pricingUnavailable}>{t.landing.pricingUnavailable}</p>
          )}
        </div>
      </section>

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
