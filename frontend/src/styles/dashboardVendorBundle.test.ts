import { execFileSync } from 'node:child_process'

import { describe, expect, it } from 'vitest'

describe('isolation du vendor dashboard dans le bundle', () => {
  it('préfixe le preflight et les utilitaires Tailwind sous la surface dashboard', () => {
    execFileSync('npm', ['run', 'build'], {
      cwd: process.cwd(),
      encoding: 'utf8',
      env: { ...process.env, NODE_ENV: 'production' },
      stdio: 'pipe',
    })

    expect(() => {
      execFileSync('node', ['scripts/assert-dashboard-css-isolation.mjs'], {
        cwd: process.cwd(),
        encoding: 'utf8',
        stdio: 'pipe',
      })
    }).not.toThrow()
  }, 30_000)
})
