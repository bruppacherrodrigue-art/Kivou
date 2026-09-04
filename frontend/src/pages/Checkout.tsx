import { useEffect, useRef, useState } from 'react'
import { CircleCheckBig, CircleX } from 'lucide-react'
import { billing } from '../api/endpoints'
import type { BillingStatus } from '../api/types'
import { clearCheckoutIntent, readCheckoutIntent } from '../billing/checkoutIntent'
import { useI18n, interpolate } from '../i18n'
import { ReferenceLink } from '../presentation/router/ReferenceLink'
import { CheckoutHandoff } from '../presentation/dashboard/CheckoutHandoff'
import { SystemState } from '../presentation/dashboard/SystemState'
import { Button } from '../presentation/dashboard/ui/button'

const POLL_INTERVAL_MS = 2500
const POLL_TIMEOUT_MS = 45_000

export function Checkout() {
  return <CheckoutHandoff />
}

/** Une URL de retour n'accorde aucun droit. Seul `/billing/status`, mis à jour
 * par le webhook Stripe, peut confirmer que le plan du compte a changé. */
export function CheckoutSuccess() {
  const { t } = useI18n()
  const [status, setStatus] = useState<BillingStatus | null>(null)
  const [intent] = useState(() => readCheckoutIntent())
  const [timedOut, setTimedOut] = useState(false)
  const [verificationRun, setVerificationRun] = useState(0)
  const mountedRef = useRef(false)
  const generationRef = useRef(0)
  const waitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const requestTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const refreshBusyRef = useRef(false)

  const confirmed = status !== null && status.plan_code !== 'discovery'

  useEffect(() => {
    mountedRef.current = true
    refreshBusyRef.current = true
    const generation = ++generationRef.current
    const deadline = Date.now() + POLL_TIMEOUT_MS

    const current = () =>
      mountedRef.current && generationRef.current === generation

    const expire = () => {
      if (!current()) return
      refreshBusyRef.current = false
      setTimedOut(true)
    }

    const poll = async () => {
      if (!current()) return
      const remaining = deadline - Date.now()
      if (remaining <= 0) {
        expire()
        return
      }

      let requestTimeout: ReturnType<typeof setTimeout> | null = null
      const attempt = billing.status().then(
        (next) => ({ kind: 'status' as const, next }),
        () => ({ kind: 'error' as const }),
      )
      const timeout = new Promise<{ kind: 'timeout' }>((resolve) => {
        requestTimeout = setTimeout(() => resolve({ kind: 'timeout' }), remaining)
        requestTimerRef.current = requestTimeout
      })
      const result = await Promise.race([attempt, timeout])
      if (requestTimeout !== null) clearTimeout(requestTimeout)
      if (requestTimerRef.current === requestTimeout) requestTimerRef.current = null
      if (!current()) return

      if (result.kind === 'timeout') {
        expire()
        return
      }
      if (result.kind === 'status') {
        if (result.next.plan_code !== 'discovery') clearCheckoutIntent()
        setStatus(result.next)
        if (result.next.plan_code !== 'discovery') {
          refreshBusyRef.current = false
          return
        }
      }

      const nextDelay = Math.min(POLL_INTERVAL_MS, deadline - Date.now())
      if (nextDelay <= 0) {
        expire()
        return
      }
      const waitTimer = setTimeout(() => {
        if (waitTimerRef.current === waitTimer) waitTimerRef.current = null
        void poll()
      }, nextDelay)
      waitTimerRef.current = waitTimer
    }

    // Le premier tour est différé afin que le montage de contrôle de
    // StrictMode puisse être nettoyé avant toute requête réelle.
    const initialTimer = setTimeout(() => {
      if (waitTimerRef.current === initialTimer) waitTimerRef.current = null
      void poll()
    }, 0)
    waitTimerRef.current = initialTimer

    return () => {
      mountedRef.current = false
      generationRef.current += 1
      refreshBusyRef.current = false
      if (waitTimerRef.current !== null) {
        clearTimeout(waitTimerRef.current)
        waitTimerRef.current = null
      }
      if (requestTimerRef.current !== null) {
        clearTimeout(requestTimerRef.current)
        requestTimerRef.current = null
      }
    }
  }, [verificationRun])

  useEffect(() => {
    if (confirmed) clearCheckoutIntent()
  }, [confirmed])

  function refresh() {
    if (refreshBusyRef.current) return
    refreshBusyRef.current = true
    setTimedOut(false)
    setVerificationRun((current) => current + 1)
  }

  const description = (
    <p role="status" aria-live="polite">
      {confirmed
        ? interpolate(t.checkout.successBody, {
            plan: t.billing.plans[status.plan_code],
          })
        : timedOut
          ? t.checkout.successTimeout
          : t.checkout.successPendingBody}
    </p>
  )

  const primary = confirmed
    ? intent
      ? { label: t.checkout.returnToSignal, href: `/app/signals/${encodeURIComponent(intent)}` }
      : { label: t.checkout.goToSignals, href: '/app/signals' }
    : undefined
  const secondary = confirmed && intent
    ? { label: t.checkout.seeAllSignals, href: '/app/signals' }
    : undefined

  return (
    <SystemState
      icon={CircleCheckBig}
      eyebrow="Retour Stripe"
      title={confirmed ? t.checkout.successTitle : t.checkout.successPending}
      description={description}
      primary={primary}
      secondary={secondary}
    >
      {!confirmed ? (
        <div className="checkout-state-links">
          <Button type="button" variant="outline" onClick={refresh} disabled={!timedOut}>
            {t.checkout.refresh}
          </Button>
        </div>
      ) : null}
      <div className="checkout-state-links">
        <ReferenceLink href="/app/billing">{t.checkout.seeBilling}</ReferenceLink>
      </div>
    </SystemState>
  )
}

/** Le retour d'annulation ne reçoit aucune preuve Stripe et n'affirme donc ni
 * échec, ni débit, ni changement de plan. */
export function CheckoutCancel() {
  const { t } = useI18n()
  useEffect(() => clearCheckoutIntent(), [])

  return (
    <SystemState
      icon={CircleX}
      eyebrow="Retour Stripe"
      title={t.checkout.cancelTitle}
      description={t.checkout.cancelBody}
      primary={{ label: t.checkout.seeBilling, href: '/app/billing' }}
      secondary={{ label: t.checkout.backToSignals, href: '/app/signals' }}
    />
  )
}
