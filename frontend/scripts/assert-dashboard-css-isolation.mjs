import fs from 'node:fs'
import path from 'node:path'

import postcss from 'postcss'

const dashboardPrefix = /^html\[data-kivou-surface=(?:"dashboard"|dashboard)\]/
const surfacePrefix = /^html\[data-kivou-surface=/
const utilitySelectors = ['.container', '.grid', '.flex', '.hidden', '.absolute', '.w-full']
const assetsDirectory = path.resolve('dist/assets')
const stylesheets = fs.readdirSync(assetsDirectory).filter((name) => /^index-.*\.css$/.test(name))

if (stylesheets.length !== 1) {
  throw new Error(`un seul bundle CSS index attendu, reçu : ${stylesheets.join(', ') || 'aucun'}`)
}

const css = fs.readFileSync(path.join(assetsDirectory, stylesheets[0]), 'utf8')
const root = postcss.parse(css)
const seenPrefixed = new Set()
let prefixedPreflight = false

root.walkRules((rule) => {
  for (const selector of rule.selectors ?? []) {
    const isDashboard = dashboardPrefix.test(selector)
    const isScoped = surfacePrefix.test(selector)
    for (const utility of utilitySelectors) {
      const containsUtility = new RegExp(`(^|[\\s>+~,(])\\${utility.replace('-', '\\-')}(?![\\w-])`).test(selector)
      if (!containsUtility) continue
      if (!isScoped) throw new Error(`utilitaire non préfixé : ${selector}`)
      if (isDashboard) seenPrefixed.add(utility)
    }
    if (selector.includes('::backdrop')) {
      if (!isDashboard) throw new Error(`preflight dashboard non préfixé : ${selector}`)
      prefixedPreflight = true
    }
  }
})

for (const utility of utilitySelectors) {
  if (!seenPrefixed.has(utility)) throw new Error(`utilitaire dashboard préfixé absent : ${utility}`)
}
if (!prefixedPreflight) throw new Error('preflight dashboard préfixé absent')

process.stdout.write(`css_dashboard_isolation=ok bundle=${stylesheets[0]}\n`)
