import { KeyRound, LogOut, ShieldCheck } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useSession } from '../auth/SessionProvider'
import { useI18n } from '../i18n'
import { PrototypeNotice } from '../presentation/dashboard/PrototypeNotice'
import { SettingsNav } from '../presentation/dashboard/SettingsNav'
import { Button } from '../presentation/dashboard/ui/button'
import { ReferenceLink } from '../presentation/router/ReferenceLink'

export function SecuritySettings() {
  const { signOut } = useSession()
  const { t } = useI18n()
  const copy = t.reference.accountSettings
  const [signingOut, setSigningOut] = useState(false)
  const mounted = useRef(true)
  const pending = useRef(false)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  async function leaveAccount() {
    if (pending.current) return
    pending.current = true
    setSigningOut(true)
    try {
      await signOut()
    } finally {
      pending.current = false
      if (mounted.current) setSigningOut(false)
    }
  }

  return (
    <div className="settings-main">
      <section className="settings-intro">
        <p className="section-label">{copy.profileLabel}</p>
        <h2>{copy.securityTitle}</h2>
        <p>{copy.securityBody}</p>
      </section>
      <SettingsNav active="security" />
      <section className="settings-form-card">
        <div className="settings-form-heading">
          <div>
            <p className="card-kicker">{copy.passwordKicker}</p>
            <h3>{copy.resetAccess}</h3>
          </div>
          <ShieldCheck aria-hidden="true" />
        </div>
        <PrototypeNotice>{copy.securityNotice}</PrototypeNotice>
        <div className="security-action-row">
          <span><KeyRound aria-hidden="true" /></span>
          <div>
            <strong>{copy.resetLinkTitle}</strong>
            <p>{copy.resetLinkBody}</p>
          </div>
          <Button asChild className="primary-action">
            <ReferenceLink href="/forgot-password">{copy.resetPassword}</ReferenceLink>
          </Button>
        </div>
        <div className="security-action-row">
          <span><LogOut aria-hidden="true" /></span>
          <div>
            <strong>{copy.logoutTitle}</strong>
            <p>{copy.logoutBody}</p>
          </div>
          <Button
            type="button"
            variant="outline"
            className="secondary-action"
            disabled={signingOut}
            onClick={() => void leaveAccount()}
          >
            {signingOut ? t.common.loading : copy.logout}
          </Button>
        </div>
      </section>
    </div>
  )
}
