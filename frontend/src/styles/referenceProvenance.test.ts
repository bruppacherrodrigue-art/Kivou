import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

it('pins both approved reference commits and their core hashes', () => {
  const manifest = JSON.parse(
    readFileSync(resolve(process.cwd(), 'reference-source.json'), 'utf8'),
  )
  expect(manifest.public.commit).toBe('efaa4160f4c3bbbdb01448bf9228772491e614f5')
  expect(manifest.dashboard.commit).toBe('05212f2da5197699e6a9bb191556afcb2dcf1bb3')
  expect(manifest.public.files['app/globals.css']).toBe(
    '56f8c96cc3975d9f81882d1ac9eb49c791aefd90d690f6a559c4a96c946bde95',
  )
  expect(manifest.dashboard.files['app/globals.css']).toBe(
    '4f7fb469e4ed2f32a424d4b45cb77e23b016314e0f2a062524f0dc7c090a720d',
  )
})
