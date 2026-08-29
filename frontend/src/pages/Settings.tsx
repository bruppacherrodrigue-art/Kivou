import { useEffect, useRef, useState } from 'react'
import { useCurrentUser, useSession } from '../auth/SessionProvider'
import { Button, ButtonLink } from '../components/Button'
import { SectionHeading } from '../components/Surfaces'
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
  const { signOut } = useSession()
  const { t } = useI18n()
  const [signingOut, setSigningOut] = useState(false)
  const mounted = useRef(true)
  const signOutPending = useRef(false)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  function leaveAccount() {
    if (signOutPending.current) return
    signOutPending.current = true
    setSigningOut(true)
    void signOut().finally(() => {
      signOutPending.current = false
      if (mounted.current) setSigningOut(false)
    })
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <SectionHeading level={1} title={t.settings.title} lead={t.settings.lead} hideTitle />
      </header>

      <section className={styles.accountSurface} aria-labelledby="account-identity">
        <header className={styles.identity}>
          <p className={styles.eyebrow}>{t.settings.identityTitle}</p>
          <h2 id="account-identity" className={styles.accountName}>
            {me.account_display_name}
          </h2>
          <p className={styles.email}>{me.email}</p>
        </header>

        <nav className={styles.actions} aria-label={t.settings.actionsLabel}>
          <div className={styles.action}>
            <div>
              <h3>{t.settings.billingTitle}</h3>
              <p>{t.settings.billingLead}</p>
            </div>
            <ButtonLink to="/app/billing" variant="secondary">
              {t.settings.billingAction}
            </ButtonLink>
          </div>

          <div className={styles.action}>
            <div>
              <h3>{t.settings.notificationsTitle}</h3>
              <p>{t.settings.notificationsLead}</p>
            </div>
            <ButtonLink to="/app/notifications" variant="secondary">
              {t.settings.notificationsAction}
            </ButtonLink>
          </div>

          <div className={styles.action}>
            <div>
              <h3>{t.settings.logoutTitle}</h3>
              <p>{t.settings.logoutLead}</p>
            </div>
            <Button variant="secondary" loading={signingOut} onClick={leaveAccount}>
              {t.nav.logout}
            </Button>
          </div>
        </nav>
      </section>
    </div>
  )
}
