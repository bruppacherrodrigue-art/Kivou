import { OnboardingFlow } from '../presentation/dashboard/OnboardingFlow'

export function Onboarding({ confirmationOnly = false }: { confirmationOnly?: boolean }) {
  return <OnboardingFlow confirmationOnly={confirmationOnly} />
}
