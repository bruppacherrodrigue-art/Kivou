import { render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { StrictMode } from 'react'
import { describe, expect, it } from 'vitest'
import { ReferenceLink } from '../reference/router/ReferenceLink'
import { SurfaceBoundary } from '../reference/surface/SurfaceBoundary'
import { renderApp, UNAUTHENTICATED } from '../test/harness'

describe('reference presentation surface', () => {
  it('sets and restores the public/dashboard surface on html', () => {
    const { rerender, unmount } = render(
      <SurfaceBoundary surface="public"><span /></SurfaceBoundary>,
    )
    expect(document.documentElement.dataset.kivouSurface).toBe('public')
    rerender(<SurfaceBoundary surface="dashboard"><span /></SurfaceBoundary>)
    expect(document.documentElement.dataset.kivouSurface).toBe('dashboard')
    unmount()
    expect(document.documentElement).not.toHaveAttribute('data-kivou-surface')
  })

  it('restores an existing empty surface attribute on html', () => {
    document.documentElement.setAttribute('data-kivou-surface', '')

    try {
      const { unmount } = render(
        <SurfaceBoundary surface="public"><span /></SurfaceBoundary>,
      )
      expect(document.documentElement.dataset.kivouSurface).toBe('public')
      unmount()
      expect(document.documentElement).toHaveAttribute('data-kivou-surface', '')
    } finally {
      document.documentElement.removeAttribute('data-kivou-surface')
    }
  })

  it('uses the exact route-owned favicon and dashboard body class', () => {
    const icon = document.createElement('link')
    icon.setAttribute('rel', 'icon')
    icon.setAttribute('href', '/original-favicon.svg')
    document.head.append(icon)

    try {
      const original = icon.getAttribute('href')
      const { rerender, unmount } = render(
        <SurfaceBoundary surface="public"><span /></SurfaceBoundary>,
      )
      expect(icon).toHaveAttribute('href', '/reference/public-favicon.svg')
      expect(document.body).not.toHaveClass('antialiased')
      rerender(<SurfaceBoundary surface="dashboard"><span /></SurfaceBoundary>)
      expect(icon).toHaveAttribute('href', '/reference/dashboard-favicon.svg')
      expect(document.body).toHaveClass('antialiased')
      unmount()
      expect(icon.getAttribute('href')).toBe(original)
      expect(document.body).not.toHaveClass('antialiased')
    } finally {
      icon.remove()
      delete document.documentElement.dataset.kivouSurface
      document.body.classList.remove('antialiased')
    }
  })

  it('restores a favicon that initially had no href attribute', () => {
    const icon = document.createElement('link')
    icon.setAttribute('rel', 'icon')
    document.head.append(icon)

    try {
      const { unmount } = render(
        <SurfaceBoundary surface="dashboard"><span /></SurfaceBoundary>,
      )
      expect(icon).toHaveAttribute('href', '/reference/dashboard-favicon.svg')
      unmount()
      expect(icon).not.toHaveAttribute('href')
    } finally {
      icon.remove()
      document.documentElement.removeAttribute('data-kivou-surface')
      document.body.classList.remove('antialiased')
    }
  })

  it('restores a favicon whose href attribute was empty', () => {
    const icon = document.createElement('link')
    icon.setAttribute('rel', 'icon')
    icon.setAttribute('href', '')
    document.head.append(icon)

    try {
      const { unmount } = render(
        <SurfaceBoundary surface="dashboard"><span /></SurfaceBoundary>,
      )
      expect(icon).toHaveAttribute('href', '/reference/dashboard-favicon.svg')
      unmount()
      expect(icon).toHaveAttribute('href', '')
    } finally {
      icon.remove()
      document.documentElement.removeAttribute('data-kivou-surface')
      document.body.classList.remove('antialiased')
    }
  })

  it('keeps the deepest nested owner active and restores the exact baseline in StrictMode', () => {
    const html = document.documentElement
    const icon = document.createElement('link')
    html.setAttribute('data-kivou-surface', 'historical')
    document.body.classList.add('antialiased')
    icon.setAttribute('rel', 'icon')
    icon.setAttribute('href', '/historical-favicon.svg')
    document.head.append(icon)

    const snapshot = () => ({
      surface: html.getAttribute('data-kivou-surface'),
      antialiased: document.body.classList.contains('antialiased'),
      favicon: icon.getAttribute('href'),
    })
    const nested = (innerSurface: 'public' | 'dashboard' | null) => (
      <StrictMode>
        <SurfaceBoundary surface="dashboard">
          {innerSurface ? (
            <SurfaceBoundary surface={innerSurface}><span /></SurfaceBoundary>
          ) : <span />}
        </SurfaceBoundary>
      </StrictMode>
    )

    try {
      const observed = []
      const { rerender, unmount } = render(nested('public'))
      observed.push(snapshot())
      rerender(nested('dashboard'))
      observed.push(snapshot())
      rerender(nested(null))
      observed.push(snapshot())
      unmount()
      observed.push(snapshot())

      expect(observed).toEqual([
        {
          surface: 'public',
          antialiased: false,
          favicon: '/reference/public-favicon.svg',
        },
        {
          surface: 'dashboard',
          antialiased: true,
          favicon: '/reference/dashboard-favicon.svg',
        },
        {
          surface: 'dashboard',
          antialiased: true,
          favicon: '/reference/dashboard-favicon.svg',
        },
        {
          surface: 'historical',
          antialiased: true,
          favicon: '/historical-favicon.svg',
        },
      ])
    } finally {
      icon.remove()
      html.removeAttribute('data-kivou-surface')
      document.body.classList.remove('antialiased')
    }
  })

  it('maps dashboard hrefs while preserving public same-origin hrefs', () => {
    renderApp(<>
      <ReferenceLink dashboard href="/signals?signal=sig_1">open signal</ReferenceLink>
      <ReferenceLink dashboard href="/checkout?plan=pro">checkout</ReferenceLink>
      <ReferenceLink href="/">public home</ReferenceLink>
    </>, { session: UNAUTHENTICATED })
    expect(screen.getByRole('link', { name: 'open signal' })).toHaveAttribute(
      'href', '/app/signals/sig_1',
    )
    expect(screen.getByRole('link', { name: 'public home' })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: 'checkout' })).toHaveAttribute(
      'href', '/checkout?plan=pro',
    )
  })

  it('does not retain the legacy no-script landing page', () => {
    const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')
    expect(html).not.toContain('LES ENTREPRISES QUI VIENNENT DE GAGNER')
    expect(html).not.toContain('<noscript>')
    expect(html).toContain('Kivou | Signaux commerciaux post-attribution')
  })

  it('restores the pinned public line-height outside the dashboard surface', () => {
    const isolationCss = readFileSync(
      resolve(process.cwd(), 'src/styles/reference-surface-isolation.css'),
      'utf8',
    )
    const main = readFileSync(resolve(process.cwd(), 'src/main.tsx'), 'utf8')

    expect(isolationCss).toMatch(
      /html\[data-kivou-surface="public"\] body\s*\{\s*line-height:\s*normal;/,
    )
    expect(isolationCss).toMatch(
      /html\[data-kivou-surface="public"\] code\s*\{\s*font-family:\s*monospace;/,
    )
    expect(isolationCss).toMatch(
      /html\[data-kivou-surface="public"\] \.legal-toc ol,[\s\S]*list-style:\s*decimal;/,
    )
    expect(isolationCss).toMatch(
      /html\[data-kivou-surface="public"\] \.legal-subsection ul\s*\{\s*list-style:\s*disc;/,
    )
    expect(isolationCss).toMatch(
      /html\[data-kivou-surface="public"\] \.legal-subsection h3\s*\{\s*font-weight:\s*700;/,
    )
    expect(isolationCss).toMatch(
      /html\[data-kivou-surface="public"\] h3\s*\{\s*font-weight:\s*700;/,
    )
    expect(isolationCss).toMatch(
      /html\[data-kivou-surface="public"\] \.card-link,[\s\S]*html\[data-kivou-surface="public"\] \.text-link,[\s\S]*html\[data-kivou-surface="public"\] \.company-lines a[\s\S]*text-decoration:\s*underline;/,
    )
    expect(isolationCss).toMatch(
      /html\[data-kivou-surface="public"\] \.legal-toc a,[\s\S]*text-decoration:\s*underline;/,
    )
    expect(main.indexOf("'./styles/reference-surface-isolation.css'")).toBeGreaterThan(
      main.indexOf("'./reference/dashboard/dashboard-reference.css'"),
    )
  })
})
