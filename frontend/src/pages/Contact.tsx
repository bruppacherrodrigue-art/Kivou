import { ButtonAnchor, ButtonLink } from '../components/Button'
import { PublicPageMeta } from '../components/PublicPageMeta'
import { Card, SectionHeading } from '../components/Surfaces'
import { useI18n } from '../i18n'
import styles from './Contact.module.css'

const CONTACT_EMAIL = 'contact@kivou.eu'

export function Contact() {
  const { t } = useI18n()

  return (
    <>
      <PublicPageMeta
        title={t.contact.metaTitle}
        description={t.contact.metaDescription}
        canonicalPath="/contact"
      />

      <article className={styles.page}>
        <div className={styles.inner}>
          <header className={styles.introduction}>
            <SectionHeading
              level={1}
              eyebrow={t.contact.eyebrow}
              title={t.contact.title}
              lead={t.contact.lead}
            />
            <div className={styles.actions}>
              <ButtonAnchor href={`mailto:${CONTACT_EMAIL}`} size="lg">
                {t.contact.emailAction}
              </ButtonAnchor>
              <ButtonLink to="/signup" variant="secondary" size="lg">
                {t.contact.signupAction}
              </ButtonLink>
            </div>
          </header>

          <div className={styles.categories}>
            {t.contact.categories.map((category, index) => (
              <Card key={category.title} className={styles.category} padding="lg" as="section">
                <p className={styles.number} aria-hidden="true">
                  {String(index + 1).padStart(2, '0')}
                </p>
                <h2>{category.title}</h2>
                <p>{category.body}</p>
              </Card>
            ))}
          </div>
        </div>
      </article>
    </>
  )
}
