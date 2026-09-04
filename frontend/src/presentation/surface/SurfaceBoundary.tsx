import {
  createContext,
  useContext,
  useLayoutEffect,
  useRef,
  type ReactNode,
} from 'react'

type Surface = 'public' | 'dashboard'

type Owner = {
  token: symbol
  parent: symbol | null
  surface: Surface
  sequence: number
}

type Baseline = {
  hadSurfaceAttribute: boolean
  surface: string | null
  bodyHadAntialiased: boolean
  icon: HTMLLinkElement | null
  iconHadHref: boolean
  iconHref: string | null
}

const SurfaceOwnerContext = createContext<symbol | null>(null)
const owners = new Map<symbol, Owner>()
let baseline: Baseline | null = null
let sequence = 0

function captureBaseline(): Baseline {
  const html = document.documentElement
  const icon = document.querySelector<HTMLLinkElement>('link[rel~="icon"]')
  return {
    hadSurfaceAttribute: html.hasAttribute('data-kivou-surface'),
    surface: html.getAttribute('data-kivou-surface'),
    bodyHadAntialiased: document.body.classList.contains('antialiased'),
    icon,
    iconHadHref: icon?.hasAttribute('href') ?? false,
    iconHref: icon?.getAttribute('href') ?? null,
  }
}

function ownerDepth(owner: Owner): number {
  let depth = 0
  let parent = owner.parent
  const visited = new Set([owner.token])
  while (parent && !visited.has(parent)) {
    const parentOwner = owners.get(parent)
    if (!parentOwner) break
    depth += 1
    visited.add(parent)
    parent = parentOwner.parent
  }
  return depth
}

function applyActiveOwner() {
  let active: Owner | null = null
  let activeDepth = -1
  for (const owner of owners.values()) {
    const depth = ownerDepth(owner)
    if (
      depth > activeDepth
      || (depth === activeDepth && owner.sequence > (active?.sequence ?? -1))
    ) {
      active = owner
      activeDepth = depth
    }
  }
  if (!active) return

  document.documentElement.dataset.kivouSurface = active.surface
  document.body.classList.toggle('antialiased', active.surface === 'dashboard')
  baseline?.icon?.setAttribute(
    'href',
    active.surface === 'public'
      ? '/presentation/public-favicon.svg'
      : '/presentation/dashboard-favicon.svg',
  )
}

function restoreBaseline() {
  if (!baseline) return

  const html = document.documentElement
  if (baseline.hadSurfaceAttribute) {
    html.setAttribute('data-kivou-surface', baseline.surface ?? '')
  } else {
    html.removeAttribute('data-kivou-surface')
  }
  document.body.classList.toggle('antialiased', baseline.bodyHadAntialiased)
  if (baseline.icon) {
    if (baseline.iconHadHref) baseline.icon.setAttribute('href', baseline.iconHref ?? '')
    else baseline.icon.removeAttribute('href')
  }
  baseline = null
}

function registerOwner(token: symbol, parent: symbol | null, surface: Surface) {
  if (owners.size === 0) baseline = captureBaseline()
  owners.set(token, { token, parent, surface, sequence: ++sequence })
  applyActiveOwner()
}

function unregisterOwner(token: symbol) {
  if (!owners.delete(token)) return
  if (owners.size > 0) applyActiveOwner()
  else restoreBaseline()
}

export function SurfaceBoundary({
  surface,
  children,
}: {
  surface: Surface
  children: ReactNode
}) {
  const parent = useContext(SurfaceOwnerContext)
  const token = useRef(Symbol('SurfaceBoundary')).current

  useLayoutEffect(() => {
    registerOwner(token, parent, surface)
    return () => unregisterOwner(token)
  }, [parent, surface, token])

  return (
    <SurfaceOwnerContext.Provider value={token}>
      {children}
    </SurfaceOwnerContext.Provider>
  )
}
