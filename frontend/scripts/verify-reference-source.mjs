import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { execFileSync } from 'node:child_process'

const manifest = JSON.parse(readFileSync(resolve('reference-source.json'), 'utf8'))

for (const [name, source] of Object.entries(manifest)) {
  const head = execFileSync('git', ['-C', source.path, 'rev-parse', 'HEAD'], {
    encoding: 'utf8',
  }).trim()
  if (head !== source.commit) throw new Error(`${name}: HEAD ${head} != ${source.commit}`)
  const dirty = execFileSync('git', ['-C', source.path, 'status', '--porcelain'], {
    encoding: 'utf8',
  }).trim()
  if (dirty) throw new Error(`${name}: source working tree is dirty`)
  for (const [relative, expected] of Object.entries(source.files)) {
    const actual = createHash('sha256')
      .update(readFileSync(resolve(source.path, relative)))
      .digest('hex')
    if (actual !== expected) throw new Error(`${name}/${relative}: hash mismatch`)
  }
}
