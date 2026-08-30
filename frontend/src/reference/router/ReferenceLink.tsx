import { Link, type LinkProps } from 'react-router-dom'

function dashboardDestination(href: string): string {
  const url = new URL(href, 'https://reference.invalid')
  if (url.pathname === '/') return '/app/dashboard'
  if (url.pathname === '/signals') {
    const signal = url.searchParams.get('signal')
    return signal ? `/app/signals/${encodeURIComponent(signal)}` : '/app/signals'
  }
  if (url.pathname === '/companies') {
    const company = url.searchParams.get('company')
    const signal = url.searchParams.get('signal')
    if (!company) return '/app/companies'
    const destination = `/app/companies/${encodeURIComponent(company)}`
    return signal ? `${destination}?signal=${encodeURIComponent(signal)}` : destination
  }
  const routes: Record<string, string> = {
    '/targeting': '/app/icps',
    '/settings': '/app/settings',
    '/settings/profile': '/app/settings/profile',
    '/settings/security': '/app/settings/security',
    '/settings/billing': '/app/billing',
    '/settings/notifications': '/app/notifications',
    '/plans': '/app/billing',
    '/billing': '/app/billing',
  }
  return `${routes[url.pathname] ?? url.pathname}${url.search}${url.hash}`
}

export function ReferenceLink({
  href,
  dashboard = false,
  ...props
}: Omit<LinkProps, 'to'> & { href: string; dashboard?: boolean }) {
  return <Link to={dashboard ? dashboardDestination(href) : href} {...props} />
}
