import { spawn, execFileSync } from 'node:child_process'
import {
  mkdirSync,
  existsSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  symlinkSync,
} from 'node:fs'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from '@playwright/test'
import { normalizePublicPricingText } from '../tests/visual/normalize-public-pricing.mjs'

const finalOutput = resolve('tests/visual/reference-goldens')
const children = []
const worktrees = []
let temporaryRoot = null
let output = null
let fontCss = ''

const pages = [
  ['public', '/', 'public-home', 'Repérez les entreprises qui viennent de gagner un marché public.'],
  ['public', '/produit', 'public-product', 'Kivou suit ce qui se passe après l’attribution.'],
  ['public', '/tarifs', 'public-pricing', 'Choisissez la couverture adaptée à votre prospection.'],
  ['public', '/exemple-de-signal', 'public-signal', 'H. Hüther GmbH a remporté un marché de 5,22 M€ à Munich.'],
  ['public', '/contact', 'public-contact', 'Contact'],
  ['public', '/informations-legales', 'public-legal', 'Informations légales et contractuelles'],
  ['dashboard', '/login', 'dashboard-login', 'Retrouver vos signaux'],
  ['dashboard', '/signup', 'dashboard-signup', 'Commencer avec un ciblage clair'],
  ['dashboard', '/', 'dashboard-overview', 'Vue d’ensemble'],
  ['dashboard', '/signals?signal=tm-ausbau-campus-ost', 'dashboard-signals', 'Signaux'],
  ['dashboard', '/companies', 'dashboard-companies', 'Entreprises'],
  ['dashboard', '/targeting', 'dashboard-targeting', 'Profil de ciblage'],
  ['dashboard', '/settings', 'dashboard-account', 'Compte'],
]

const expectedGoldens = [
  ...pages.flatMap(([, , name]) => [name + '-desktop.png', name + '-mobile.png']),
  'public-menu-open-mobile.png',
  'dashboard-sidebar-open-mobile.png',
].sort()

function addWorktree(source, name) {
  if (!temporaryRoot) throw new Error('temporary root is not initialized')
  const target = join(temporaryRoot, name)
  execFileSync('git', ['-C', source.path, 'worktree', 'add', '--detach', target, source.commit], {
    stdio: 'inherit',
  })
  worktrees.push({ repository: source.path, target })
  symlinkSync(join(source.path, 'node_modules'), join(target, 'node_modules'), 'dir')
  return target
}

function start(cwd, port) {
  const child = spawn(
    'npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(port), '--strictPort'],
    { cwd, detached: true, stdio: ['ignore', 'pipe', 'pipe'] },
  )
  child.referenceLog = ''
  child.referenceSpawnError = null
  child.once('error', (error) => { child.referenceSpawnError = error })
  child.stdout.on('data', (chunk) => { child.referenceLog += chunk.toString() })
  child.stderr.on('data', (chunk) => { child.referenceLog += chunk.toString() })
  children.push(child)
  return child
}

async function freePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer()
    server.unref()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      if (!address || typeof address === 'string') {
        server.close()
        reject(new Error('could not allocate a reference capture port'))
        return
      }
      const port = address.port
      server.close((error) => error ? reject(error) : resolvePort(port))
    })
  })
}

async function ready(url, child, heading) {
  const deadline = Date.now() + 60_000
  let lastObservation = 'no response'
  while (Date.now() < deadline) {
    if (child.referenceSpawnError) {
      throw new Error('reference server could not spawn: ' + child.referenceSpawnError.message)
    }
    if (child.exitCode !== null) {
      throw new Error(
        'reference server exited before readiness (' + child.exitCode + '):\n' + child.referenceLog,
      )
    }
    try {
      const response = await fetch(url)
      const body = await response.text()
      lastObservation = response.status + ' ' + body.slice(0, 160)
      if (response.ok && body.includes(heading)) return
    } catch (error) {
      lastObservation = error instanceof Error ? error.message : String(error)
    }
    await new Promise((accept) => setTimeout(accept, 250))
  }
  throw new Error(
    'reference server did not become ready: ' + url + '\n'
      + lastObservation + '\n' + child.referenceLog,
  )
}

async function normalizeConnectedText(page) {
  await page.evaluate(() => {
    const roots = document.querySelectorAll('.dashboard-provider, .auth-page, [role="dialog"]')
    for (const root of roots) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
      const nodes = []
      while (walker.nextNode()) nodes.push(walker.currentNode)
      const normalizedParents = new Set()
      for (const node of nodes) {
        if (!node.nodeValue?.trim()) continue
        const parent = node.parentNode
        if (parent && normalizedParents.has(parent)) node.nodeValue = ''
        else {
          node.nodeValue = 'Texte'
          if (parent) normalizedParents.add(parent)
        }
      }
      for (const field of root.querySelectorAll('input, textarea')) {
        field.setAttribute('placeholder', 'Texte')
        if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
          field.value = ''
        }
      }
    }
  })
}

async function installDeterministicFonts(page) {
  await page.addStyleTag({ content: fontCss })
  await page.evaluate(async () => {
    await document.fonts.load('400 16px "Instrument Sans Variable"')
    await document.fonts.load('400 16px "Lora Variable"')
    await document.fonts.ready
    if (
      !document.fonts.check('400 16px "Instrument Sans Variable"')
      || !document.fonts.check('400 16px "Lora Variable"')
    ) {
      throw new Error('deterministic reference fonts did not load')
    }
  })
}

async function capture(page, site, base, path, name, heading, viewportName) {
  if (!output) throw new Error('capture output is not initialized')
  await page.setViewportSize(viewportName === 'desktop'
    ? { width: 1440, height: 900 }
    : { width: 390, height: 844 })
  await page.goto(base + path, { waitUntil: 'networkidle' })
  await installDeterministicFonts(page)
  await page.getByRole('heading', { level: 1, name: heading, exact: true }).waitFor()
  if (site === 'dashboard') await normalizeConnectedText(page)
  if (
    name === 'public-home'
    || name === 'public-product'
    || name === 'public-pricing'
    || name === 'public-signal'
  ) {
    await normalizePublicPricingText(page)
  }
  await page.screenshot({
    path: join(output, name + '-' + viewportName + '.png'),
    fullPage: true,
    animations: 'disabled',
  })
}

async function cleanup() {
  const errors = []
  for (const child of [...children].reverse()) {
    if (child.pid) {
      try { process.kill(-child.pid, 'SIGTERM') } catch (error) {
        if (error?.code !== 'ESRCH') errors.push(error)
      }
    }
  }
  await new Promise((accept) => setTimeout(accept, 500))
  for (const child of [...children].reverse()) {
    if (child.pid) {
      try { process.kill(-child.pid, 'SIGKILL') } catch (error) {
        if (error?.code !== 'ESRCH') errors.push(error)
      }
    }
  }
  for (const { repository, target } of [...worktrees].reverse()) {
    try {
      execFileSync('git', ['-C', repository, 'worktree', 'remove', '--force', target], {
        stdio: 'inherit',
      })
    } catch (error) {
      errors.push(error)
    }
  }
  if (temporaryRoot) {
    try { rmSync(temporaryRoot, { recursive: true, force: true }) } catch (error) {
      errors.push(error)
    }
  }
  if (output) {
    try { rmSync(output, { recursive: true, force: true }) } catch (error) {
      errors.push(error)
    }
  }
  return errors
}

async function main() {
  let primaryError = null
  try {
    execFileSync(process.execPath, ['scripts/verify-reference-source.mjs'], { stdio: 'inherit' })
    const manifest = JSON.parse(readFileSync(resolve('reference-source.json'), 'utf8'))
    temporaryRoot = execFileSync(
      'mktemp',
      ['-d', join(tmpdir(), 'kivou-reference.XXXXXX')],
      { encoding: 'utf8' },
    ).trim()
    output = resolve('tests/visual/.reference-goldens-next-' + process.pid)
    rmSync(output, { recursive: true, force: true })
    mkdirSync(output, { recursive: true })

    const font = (path) => readFileSync(resolve(path)).toString('base64')
    fontCss = [
      '@font-face { font-family: "Instrument Sans Variable"; src: url(data:font/woff2;base64,' + font('node_modules/@fontsource-variable/instrument-sans/files/instrument-sans-latin-wght-normal.woff2') + ') format("woff2"); font-weight: 100 900; font-style: normal; font-display: block; }',
      '@font-face { font-family: "Lora Variable"; src: url(data:font/woff2;base64,' + font('node_modules/@fontsource-variable/lora/files/lora-latin-wght-normal.woff2') + ') format("woff2"); font-weight: 400 700; font-style: normal; font-display: block; }',
      '*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }',
    ].join('\n')

    const publicTree = addWorktree(manifest.public, 'public')
    const dashboardTree = addWorktree(manifest.dashboard, 'dashboard')
    const [publicPort, dashboardPort] = await Promise.all([freePort(), freePort()])
    if (publicPort === dashboardPort) throw new Error('reference ports unexpectedly collided')
    const publicChild = start(publicTree, publicPort)
    const dashboardChild = start(dashboardTree, dashboardPort)
    const publicBase = 'http://127.0.0.1:' + publicPort
    const dashboardBase = 'http://127.0.0.1:' + dashboardPort
    await Promise.all([
      ready(publicBase + '/', publicChild, pages[0][3]),
      ready(dashboardBase + '/', dashboardChild, 'Vue d’ensemble'),
    ])

    const browser = await chromium.launch()
    try {
      const page = await browser.newPage({
        locale: 'fr-CH',
        timezoneId: 'UTC',
        colorScheme: 'light',
        reducedMotion: 'reduce',
        deviceScaleFactor: 1,
      })
      const browserFailures = []
      page.on('pageerror', (error) => browserFailures.push('pageerror: ' + error.message))
      page.on('console', (message) => {
        if (message.type() === 'error') browserFailures.push('console: ' + message.text())
      })
      page.on('requestfailed', (request) => {
        browserFailures.push('requestfailed: ' + request.method() + ' ' + request.url())
      })

      for (const [site, path, name, heading] of pages) {
        const base = site === 'public' ? publicBase : dashboardBase
        await capture(page, site, base, path, name, heading, 'desktop')
        await capture(page, site, base, path, name, heading, 'mobile')
      }

      await page.setViewportSize({ width: 390, height: 844 })
      await page.goto(publicBase + '/', { waitUntil: 'networkidle' })
      await installDeterministicFonts(page)
      await normalizePublicPricingText(page)
      await page.locator('summary[aria-label="Ouvrir le menu"]').click()
      await page.screenshot({
        path: join(output, 'public-menu-open-mobile.png'),
        fullPage: true,
        animations: 'disabled',
      })

      await page.goto(dashboardBase + '/', { waitUntil: 'networkidle' })
      await installDeterministicFonts(page)
      await page.getByRole('button', { name: 'Ouvrir la navigation' }).click()
      await normalizeConnectedText(page)
      await page.screenshot({
        path: join(output, 'dashboard-sidebar-open-mobile.png'),
        fullPage: true,
        animations: 'disabled',
      })

      if (browserFailures.length > 0) {
        throw new Error('reference browser failures:\n' + browserFailures.join('\n'))
      }
    } finally {
      await browser.close()
    }

    const actualGoldens = readdirSync(output).sort()
    if (JSON.stringify(actualGoldens) !== JSON.stringify(expectedGoldens)) {
      throw new Error(
        'reference golden set mismatch\nexpected: ' + expectedGoldens.join(', ')
          + '\nactual: ' + actualGoldens.join(', '),
      )
    }
    const previousOutput = resolve('tests/visual/.reference-goldens-previous-' + process.pid)
    rmSync(previousOutput, { recursive: true, force: true })
    if (existsSync(finalOutput)) renameSync(finalOutput, previousOutput)
    try {
      renameSync(output, finalOutput)
    } catch (error) {
      if (existsSync(previousOutput) && !existsSync(finalOutput)) {
        renameSync(previousOutput, finalOutput)
      }
      throw error
    }
    rmSync(previousOutput, { recursive: true, force: true })
    output = null
  } catch (error) {
    primaryError = error
  } finally {
    const cleanupErrors = await cleanup()
    if (cleanupErrors.length > 0) {
      primaryError = primaryError
        ? new AggregateError([primaryError, ...cleanupErrors], 'reference capture and cleanup failed')
        : new AggregateError(cleanupErrors, 'reference capture cleanup failed')
    }
  }
  if (primaryError) throw primaryError
}

await main()
