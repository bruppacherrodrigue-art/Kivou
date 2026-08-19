import { useI18n } from '../i18n'
import { EmptyState } from '../components/Surfaces'
import { ButtonLink } from '../components/Button'
import { NoSignalIllustration } from '../assets/Illustrations'

export function NotFound() {
  const { t } = useI18n()
  return (
    <main id="kivou-main">
      <EmptyState
        illustration={<NoSignalIllustration />}
        title={t.errors.notFoundTitle}
        body={t.errors.notFoundBody}
        action={<ButtonLink to="/">{t.errors.goHome}</ButtonLink>}
      />
    </main>
  )
}
