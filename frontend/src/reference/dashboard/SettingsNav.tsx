import { useI18n } from '../../i18n'
import { ReferenceLink } from '../router/ReferenceLink'

export type SettingsView = 'overview' | 'profile' | 'security' | 'notifications' | 'billing'

const settingsLinks = [
  { id: 'overview', href: '/settings' },
  { id: 'profile', href: '/settings/profile' },
  { id: 'security', href: '/settings/security' },
  { id: 'notifications', href: '/settings/notifications' },
  { id: 'billing', href: '/settings/billing' },
] as const

export function SettingsNav({ active }: { active: SettingsView }) {
  const { t } = useI18n()

  return (
    <nav className="settings-nav" aria-label={t.reference.accountSettings.navLabel}>
      {settingsLinks.map((link) => (
        <ReferenceLink
          dashboard
          className={link.id === active ? 'is-active' : ''}
          aria-current={link.id === active ? 'page' : undefined}
          href={link.href}
          key={link.id}
        >
          {t.reference.accountSettings.nav[link.id]}
        </ReferenceLink>
      ))}
    </nav>
  )
}
