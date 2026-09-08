#!/usr/bin/env node

import { readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import ts from 'typescript'

const root = resolve(new URL('..', import.meta.url).pathname, 'src')
const dictionaries = ['i18n/fr.ts', 'i18n/en.ts']

// These are deliberately reviewed exceptions. They are accessed through a
// variable or a dictionary key rather than `t.foo.bar`.
const DYNAMIC_PREFIXES = [
  'reference.status',
  'billing.plans',
  'billing.planPositioning',
  'billing.entitlements',
  'signals.filters.periodOptions',
]

function filesUnder(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory() && entry.name !== 'i18n' && entry.name !== 'node_modules') return filesUnder(path)
    return entry.isFile() && /\.(ts|tsx)$/.test(entry.name) ? [path] : []
  })
}

function propertyName(node) {
  if (!node.name) return null
  if (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name)) return node.name.text
  return null
}

function objectRoot(source, variable) {
  let found = null
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === variable && node.initializer && ts.isObjectLiteralExpression(node.initializer)) found = node.initializer
    ts.forEachChild(node, visit)
  }
  visit(source)
  return found
}

function leaves(node, prefix = '', output = []) {
  for (const property of node.properties) {
    const name = propertyName(property)
    if (!name || !ts.isPropertyAssignment(property)) continue
    const path = prefix ? `${prefix}.${name}` : name
    if (ts.isObjectLiteralExpression(property.initializer)) leaves(property.initializer, path, output)
    else if (!ts.isArrayLiteralExpression(property.initializer)) output.push({ path, node: property })
  }
  return output
}

function accessChains(source) {
  const chains = new Set()
  function visit(node) {
    if (ts.isPropertyAccessExpression(node)) {
      const chain = node.getText(source)
      const parts = chain.split('.')
      for (let index = 0; index < parts.length; index += 1) chains.add(parts.slice(index).join('.'))
    } else if (ts.isElementAccessExpression(node) && node.argumentExpression && ts.isStringLiteral(node.argumentExpression)) {
      chains.add(node.argumentExpression.text)
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return chains
}

const sourceFiles = filesUnder(root)
const chains = new Set(DYNAMIC_PREFIXES)
for (const path of sourceFiles) {
  const source = ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true)
  for (const chain of accessChains(source)) chains.add(chain)
}

const allLeaves = []
for (const relativePath of dictionaries) {
  const path = resolve(root, relativePath)
  const source = ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true)
  const variable = relativePath.includes('/fr.') ? 'fr' : 'en'
  allLeaves.push(...leaves(objectRoot(source, variable)).map((leaf) => ({ ...leaf, filePath: path, source })))
}

const isUsed = (path) => [...chains].some((chain) => chain === path || chain.endsWith(`.${path}`) || path.startsWith(`${chain}.`))
const orphan = allLeaves.filter((leaf) => !isUsed(leaf.path))
const report = {
  dictionary_leaves: allLeaves.length,
  orphan_leaves: orphan.length,
  dynamic_prefixes: DYNAMIC_PREFIXES,
  orphan_paths: [...new Set(orphan.map((leaf) => leaf.path))].sort(),
}

if (!process.argv.includes('--prune')) {
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`)
  process.exit(0)
}

for (const path of dictionaries.map((entry) => resolve(root, entry))) {
  const sourceText = readFileSync(path, 'utf8')
  const source = ts.createSourceFile(path, sourceText, ts.ScriptTarget.Latest, true)
  const variable = path.endsWith('/fr.ts') ? 'fr' : 'en'
  const factory = ts.factory
  const transformObject = (node, prefix) => factory.updateObjectLiteralExpression(node, node.properties.filter((property) => {
    const name = propertyName(property)
    if (!name || !ts.isPropertyAssignment(property)) return true
    const key = prefix ? `${prefix}.${name}` : name
    if (ts.isObjectLiteralExpression(property.initializer)) {
      const child = transformObject(property.initializer, key)
      return isUsed(key) || child.properties.length > 0
    }
    return isUsed(key)
  }).map((property) => {
    const name = propertyName(property)
    if (!name || !ts.isPropertyAssignment(property) || !ts.isObjectLiteralExpression(property.initializer)) return property
    const key = prefix ? `${prefix}.${name}` : name
    return factory.createPropertyAssignment(property.name, transformObject(property.initializer, key))
  }))
  const transformer = (context) => (root) => {
    const visit = (node) => {
      if (ts.isVariableDeclaration(node) && node.name.getText(source) === variable && node.initializer && ts.isObjectLiteralExpression(node.initializer)) {
        return factory.updateVariableDeclaration(node, node.name, node.exclamationToken, node.type, transformObject(node.initializer, ''))
      }
      return ts.visitEachChild(node, visit, context)
    }
    return ts.visitNode(root, visit)
  }
  const result = ts.transform(source, [transformer])
  writeFileSync(path, ts.createPrinter({ newLine: ts.NewLineKind.LineFeed }).printFile(result.transformed[0]))
  result.dispose()
}
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`)
