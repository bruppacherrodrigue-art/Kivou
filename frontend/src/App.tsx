import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { I18nProvider, useI18n } from './i18n'
import { SessionProvider, accountLocale, useSession } from './auth/SessionProvider'
import { RedirectIfAuthenticated, RequireAuth } from './auth/RequireAuth'
import { PublicLayout } from './layouts/PublicLayout'
import { AppShell } from './layouts/AppShell'
import { Landing } from './pages/Landing'
import { DashboardDemoCapture } from './pages/DashboardDemoCapture'
import { PublicSignalDemo } from './pages/PublicSignalDemo'
import { LegalInformation } from './pages/LegalInformation'
import { Contact } from './pages/Contact'
import { Login } from './pages/Login'
import { Signup } from './pages/Signup'
import { ForgotPassword, ResetPassword } from './pages/PasswordReset'
import { Onboarding } from './pages/Onboarding'
import { SignalsFeed } from './pages/SignalsFeed'
import { SignalDetail } from './pages/SignalDetail'
import { Icps } from './pages/Icps'
import { Billing } from './pages/Billing'
import { Notifications } from './pages/Notifications'
import { CommercialCockpit } from './cockpit/CommercialCockpit'
import { CheckoutCancel, CheckoutSuccess } from './pages/Checkout'
import { NotFound } from './pages/NotFound'

/* Les routes.
 *
 * Le préfixe `/app` évite toute collision avec l'API servie sur la MÊME
 * origine : `GET /signals` appartient au backend, `/app/signals` au navigateur.
 * Sans ce préfixe, les deux se disputeraient le même chemin derrière le proxy
 * inverse.
 *
 * `/billing/success` et `/billing/cancel` sont les valeurs PAR DÉFAUT de
 * `stripe_success_url` et `stripe_cancel_url` dans `ApiConfig`. La SPEC demande
 * `/checkout/success` et `/checkout/cancel` ; les deux couples sont donc
 * servis, et les URL canoniques restent celles de la SPEC. Aucun changement
 * backend n'est nécessaire — ces valeurs sont configurables par variable
 * d'environnement — mais le parcours reste intact si elles ne le sont pas.
 */
export function App() {
  return (
    <I18nProvider>
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    </I18nProvider>
  )
}

/* Les routes, séparées des fournisseurs.
 *
 * Le découpage n'est pas cosmétique : les tests montent leurs propres
 * fournisseurs pour injecter une session déterministe. Si `App` imbriquait
 * inconditionnellement les siens, l'état injecté serait ignoré et chaque test
 * repartirait d'un appel réseau à `/me`. */
export function AppRoutes() {
  return (
    <>
      <LocaleFollowsAccount />
      <Routes>
        {import.meta.env.DEV ? (
          <Route path="__capture/dashboard-demo" element={<DashboardDemoCapture />} />
        ) : null}
        <Route element={<PublicLayout />}>
          <Route index element={<Landing />} />
          {/* Publique et sans garde : un visiteur doit pouvoir examiner un
            signal complet sans compte, et sans qu'aucun appel de session ne
            soit requis pour rendre la page. */}
          <Route path="exemple-de-signal" element={<PublicSignalDemo />} />
          <Route path="informations-legales" element={<LegalInformation />} />
          <Route path="contact" element={<Contact />} />
          {/* Compatibilité des anciennes URL : `replace` évite d'emprisonner
              le bouton précédent sur la redirection, tandis que HashTarget
              déplace ensuite le focus vers la section canonique. */}
          <Route
            path="mentions-legales"
            element={<Navigate to="/informations-legales#mentions-legales" replace />}
          />
          <Route
            path="confidentialite"
            element={<Navigate to="/informations-legales#confidentialite" replace />}
          />
          <Route path="cgu" element={<Navigate to="/informations-legales#cgu" replace />} />

          <Route element={<RedirectIfAuthenticated />}>
            <Route path="login" element={<Login />} />
            <Route path="signup" element={<Signup />} />
          </Route>

          <Route path="forgot-password" element={<ForgotPassword />} />
          <Route path="reset-password" element={<ResetPassword />} />
        </Route>

        <Route element={<RequireAuth />}>
          <Route path="onboarding" element={<Onboarding />} />

          <Route path="app" element={<AppShell />}>
            <Route index element={<Navigate to="/app/signals" replace />} />
            <Route path="signals" element={<SignalsFeed />} />
            <Route path="signals/:signalKey" element={<SignalDetail />} />
            <Route path="icps" element={<Icps />} />
            <Route path="billing" element={<Billing />} />
            <Route path="notifications" element={<Notifications />} />
            <Route path="internal/cockpit" element={<CommercialCockpit />} />
          </Route>

          <Route path="checkout/success" element={<CheckoutSuccess />} />
          <Route path="checkout/cancel" element={<CheckoutCancel />} />
          {/* Alias des URL de retour Stripe par défaut. */}
          <Route path="billing/success" element={<Navigate to="/checkout/success" replace />} />
          <Route path="billing/cancel" element={<Navigate to="/checkout/cancel" replace />} />
          <Route path="billing" element={<Navigate to="/app/billing" replace />} />
        </Route>

        <Route path="*" element={<NotFound />} />
      </Routes>
    </>
  )
}

/** Une fois connecté, `account.locale` fait autorité — l'API renvoie déjà ses
 *  libellés dans cette langue, et laisser l'interface en choisir une autre
 *  ferait cohabiter deux langues sur le même écran. */
function LocaleFollowsAccount() {
  const { state } = useSession()
  const { locale, setLocale } = useI18n()

  useEffect(() => {
    const accountValue = accountLocale(state.status === 'authenticated' ? state.me : null)
    if (accountValue && accountValue !== locale) setLocale(accountValue)
  }, [state, locale, setLocale])

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  return null
}
