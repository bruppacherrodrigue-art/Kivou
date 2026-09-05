import tailwind from '@tailwindcss/postcss'

const surfaceByFile = new Map([
  ['public-reference.css', 'public'],
  ['marketing.css', 'public'],
  ['dashboard-reference.css', 'dashboard'],
  ['dashboard-vendor.css', 'dashboard'],
  ['shadcn-tailwind-4.13.0.css', 'dashboard'],
])

function scopeReferenceCss() {
  const prefixSelector = (selector, prefix) => {
    if (selector.startsWith(prefix)) return selector
    if (selector === ':root' || selector === 'html') return prefix
    if (selector === 'body') return `${prefix} body`
    if (selector.startsWith('html ')) return `${prefix} ${selector.slice(5)}`
    return `${prefix} ${selector}`
  }

  const scopeRule = (rule, prefix) => {
    for (let parent = rule.parent; parent; parent = parent.parent) {
      if (parent.type === 'atrule' && /keyframes$/i.test(parent.name)) return
    }
    rule.selectors = rule.selectors.map((selector) => prefixSelector(selector, prefix))
  }

  return {
    postcssPlugin: 'scope-kivou-reference-css',
    Rule(rule) {
      const file = rule.source?.input.file ?? ''
      const name = [...surfaceByFile.keys()].find((candidate) => file.endsWith(candidate))
      if (!name) return
      const prefix = `html[data-kivou-surface="${surfaceByFile.get(name)}"]`
      scopeRule(rule, prefix)
    },
    OnceExit(root) {
      root.walkRules((rule) => {
        const file = rule.source?.input.file ?? ''
        const name = [...surfaceByFile.keys()].find((candidate) => file.endsWith(candidate))
        if (!name) return
        const prefix = `html[data-kivou-surface="${surfaceByFile.get(name)}"]`
        scopeRule(rule, prefix)
      })
    },
  }
}
scopeReferenceCss.postcss = true

export default { plugins: [tailwind(), scopeReferenceCss()] }
