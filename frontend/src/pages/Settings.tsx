import { useCurrentUser } from '../auth/SessionProvider'
import { ButtonLink } from '../components/Button'
import { Card, DataList, DataRow, SectionHeading } from '../components/Surfaces'
import { useI18n } from '../i18n'
import styles from './Settings.module.css'

/* Une page de compte volontairement courte.
 *
 * Elle relie les fonctions réellement disponibles. Aucun changement de nom,
 * de langue, de fuseau ou de mot de passe n'est simulé tant qu'aucune API ne le
 * permet.
 */
export function Settings() {
  const me = useCurrentUser()
  const { t } = useI18n()

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <SectionHeading level={1} title={t.settings.title} lead={t.settings.lead} />
      </header>

      <div className={styles.grid}>
        <Card as="section" padding="lg" className={styles.identity}>
          <SectionHeading title={t.settings.identityTitle} />
          <DataList>
            <DataRow label={t.settings.company}>{me.account_display_name}</DataRow>
            <DataRow label={t.settings.email}>{me.email}</DataRow>
          </DataList>
        </Card>

        <Card as="section" padding="lg" className={styles.card}>
          <SectionHeading title={t.settings.billingTitle} lead={t.settings.billingLead} />
          <ButtonLink to="/app/billing" variant="secondary">
            {t.settings.billingAction}
          </ButtonLink>
        </Card>

        <Card as="section" padding="lg" className={styles.card}>
          <SectionHeading
            title={t.settings.notificationsTitle}
            lead={t.settings.notificationsLead}
          />
          <ButtonLink to="/app/notifications" variant="secondary">
            {t.settings.notificationsAction}
          </ButtonLink>
        </Card>
      </div>
    </div>
  )
}
