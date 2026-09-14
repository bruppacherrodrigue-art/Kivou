import { execFileSync } from 'node:child_process'

import { describe, expect, it } from 'vitest'

describe('isolation du vendor dashboard dans le bundle', () => {
  it('préfixe le preflight et les utilitaires Tailwind sous la surface dashboard', () => {
    execFileSync('npm', ['run', 'build'], {
      cwd: process.cwd(),
      encoding: 'utf8',
      env: { ...process.env, NODE_ENV: 'production' },
      stdio: 'pipe',
      timeout: 90_000,
    })

    expect(() => {
      execFileSync('node', ['scripts/assert-dashboard-css-isolation.mjs'], {
        cwd: process.cwd(),
        encoding: 'utf8',
        stdio: 'pipe',
        timeout: 10_000,
      })
    }).not.toThrow()
  // This integration test builds the entire product (48.7 s measured under
  // parallel CPU load), not just a component. Bound child processes as well;
  // keep every CSS-isolation assertion and the global unit timeout unchanged.
  }, 105_000)
})
