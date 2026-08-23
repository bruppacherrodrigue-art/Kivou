import { Navigate } from 'react-router-dom'
import { useCurrentUser } from '../auth/SessionProvider'
import { SectionHeading } from '../components/Surfaces'
import { useI18n } from '../i18n'

export function Dashboard() {
  const me = useCurrentUser()

  if (me.onboarding_status !== 'ready_for_signals') {
    return <Navigate to="/onboarding" replace />
  }

  return <ReadyDashboard />
}

function ReadyDashboard() {
  const { t } = useI18n()

  return <SectionHeading level={1} title={t.dashboard.title} />
}
