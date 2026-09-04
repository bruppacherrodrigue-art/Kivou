import { AuthFlow } from '../presentation/dashboard/AuthFlow'

export function ForgotPassword() {
  return <AuthFlow mode="forgot" />
}

export function ResetPassword() {
  return <AuthFlow mode="reset" />
}
