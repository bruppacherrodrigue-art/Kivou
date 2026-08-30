import { useLayoutEffect } from 'react'
import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { I18nProvider, useI18n } from './i18n'
import { SessionProvider, accountLocale, useSession } from './auth/SessionProvider'
import { RedirectIfAuthenticated, RequireAuth } from './auth/RequireAuth'
import { PublicLayout } from './layouts/PublicLayout'
import { AppShell } from './layouts/AppShell'
import { Landing } from './pages/Landing'
import { PublicSignalDemo } from './pages/PublicSignalDemo'
import { LegalInformation } from './pages/LegalInformation'
import { Contact } from './pages/Contact'
import { Product } from './pages/Product'
import { PublicPricing } from './pages/PublicPricing'
import { Login } from './pages/Login'
import { Signup } from './pages/Signup'
import { ForgotPassword, ResetPassword } from './pages/PasswordReset'
import { Onboarding } from './pages/Onboarding'
import { Dashboard } from './pages/Dashboard'
import { SignalsFeed } from './pages/SignalsFeed'
import { Companies } from './pages/Companies'
import { Icps } from './pages/Icps'
import { Billing } from './pages/Billing'
import { Notifications } from './pages/Notifications'
import { Settings } from './pages/Settings'
import { ProfileSettings } from './pages/ProfileSettings'
import { SecuritySettings } from './pages/SecuritySettings'
import { Checkout, CheckoutCancel, CheckoutSuccess } from './pages/Checkout'
import { NotFound } from './pages/NotFound'
import { SurfaceBoundary } from './reference/surface/SurfaceBoundary'

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
    <Routes>
      <Route element={<RouteLocaleBoundary connected={false} />}>
        <Route element={<PublicLayout />}>
          <Route index element={<Landing />} />
          <Route path="produit" element={<Product />} />
          <Route path="tarifs" element={<PublicPricing />} />
          <Route path="exemple-de-signal" element={<PublicSignalDemo />} />
          <Route path="contact" element={<Contact />} />
          <Route path="informations-legales" element={<LegalInformation />} />
          <Route
            path="mentions-legales"
            element={<Navigate to="/informations-legales#mentions-legales" replace />}
          />
          <Route
            path="confidentialite"
            element={<Navigate to="/informations-legales#confidentialite" replace />}
          />
          <Route path="cgu" element={<Navigate to="/informations-legales#cgu" replace />} />
          <Route path="*" element={<NotFound />} />
        </Route>

        <Route element={<DashboardSurface />}>
          <Route element={<RedirectIfAuthenticated />}>
            <Route path="login" element={<Login />} />
            <Route path="signup" element={<Signup />} />
          </Route>

          <Route path="forgot-password" element={<ForgotPassword />} />
          <Route path="reset-password" element={<ResetPassword />} />
        </Route>
      </Route>

      <Route element={<RouteLocaleBoundary connected />}>
        <Route element={<DashboardSurface />}>
          <Route element={<RequireAuth />}>
            <Route path="onboarding" element={<Onboarding />} />
            <Route path="checkout" element={<Checkout />} />

            <Route path="app" element={<AppShell />}>
              <Route index element={<Navigate to="/app/dashboard" replace />} />
              <Route path="dashboard" element={<Dashboard />} />
              <Route path="signals" element={<SignalsFeed />} />
              <Route path="signals/:signalKey" element={<SignalsFeed />} />
              <Route path="companies" element={<Companies />} />
              <Route path="companies/:companyKey" element={<Companies />} />
              <Route path="icps" element={<Icps />} />
              <Route path="billing" element={<Billing />} />
              <Route path="notifications" element={<Notifications />} />
              <Route path="settings" element={<Settings />} />
              <Route path="settings/profile" element={<ProfileSettings />} />
              <Route path="settings/security" element={<SecuritySettings />} />
            </Route>

            <Route path="checkout/success" element={<CheckoutSuccess />} />
            <Route path="checkout/cancel" element={<CheckoutCancel />} />
            <Route path="billing/success" element={<Navigate to="/checkout/success" replace />} />
            <Route path="billing/cancel" element={<Navigate to="/checkout/cancel" replace />} />
            <Route path="billing" element={<Navigate to="/app/billing" replace />} />
          </Route>
        </Route>
      </Route>
    </Routes>
  )
}

function DashboardSurface() {
  return (
    <SurfaceBoundary surface="dashboard">
      <Outlet />
    </SurfaceBoundary>
  )
}

/** Une fois connecté, `account.locale` fait autorité — l'API renvoie déjà ses
 *  libellés dans cette langue, et laisser l'interface en choisir une autre
 *  ferait cohabiter deux langues sur le même écran.
 *
 * @internal Exposée pour tester la frontière de rendu sans dupliquer son contrat. */
export function RouteLocaleBoundary({ connected }: { connected: boolean }) {
  const { state } = useSession()
  const { locale, setLocale } = useI18n()
  const wanted =
    connected && state.status === 'authenticated'
      ? accountLocale(state.me) ?? 'fr'
      : 'fr'

  useLayoutEffect(() => {
    if (wanted !== locale) setLocale(wanted)
    else document.documentElement.lang = wanted
  }, [wanted, locale, setLocale])

  if (locale !== wanted) return null
  return <Outlet />
}
