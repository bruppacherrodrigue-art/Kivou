import tailwind from '@tailwindcss/postcss'

const surfaceByFile = new Map([
  ['public-reference.css', 'public'],
  ['dashboard-reference.css', 'dashboard'],
  ['shadcn-tailwind-4.13.0.css', 'dashboard'],
])

function scopeReferenceCss() {
  return {
    postcssPlugin: 'scope-kivou-reference-css',
    Rule(rule) {
      const file = rule.source?.input.file ?? ''
      const name = [...surfaceByFile.keys()].find((candidate) => file.endsWith(candidate))
      if (!name) return
      for (let parent = rule.parent; parent; parent = parent.parent) {
        if (parent.type === 'atrule' && /keyframes$/i.test(parent.name)) return
      }
      const prefix = `html[data-kivou-surface="${surfaceByFile.get(name)}"]`
      rule.selectors = rule.selectors.map((selector) => {
        if (selector === ':root' || selector === 'html') return prefix
        if (selector === 'body') return `${prefix} body`
        if (selector.startsWith('html ')) return `${prefix} ${selector.slice(5)}`
        return `${prefix} ${selector}`
      })
    },
  }
}
scopeReferenceCss.postcss = true

export default { plugins: [tailwind(), scopeReferenceCss()] }
