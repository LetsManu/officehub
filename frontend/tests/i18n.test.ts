import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import de from '../src/locales/de'
import en from '../src/locales/en'

function flatten(node: unknown, prefix = ''): Map<string, string> {
  const out = new Map<string, string>()
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'string') out.set(path, value)
    else for (const [k, v] of flatten(value, path)) out.set(k, v)
  }
  return out
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'locales' ? [] : sourceFiles(path)
    return /\.(vue|ts)$/.test(name) ? [path] : []
  })
}

const deKeys = flatten(de)
const enKeys = flatten(en)
const source = sourceFiles(join(__dirname, '../src')).map((f) => readFileSync(f, 'utf8')).join('\n')

describe('translations', () => {
  it('German and English have the same keys', () => {
    expect([...enKeys.keys()].sort()).toEqual([...deKeys.keys()].sort())
  })

  it('every key used with t() exists', () => {
    const used = [...source.matchAll(/\bt\(\s*'([\w.]+)'/g)].map((m) => m[1])
    const missing = used.filter((key) => !deKeys.has(key))
    expect(missing).toEqual([])
  })

  it('every dynamic key prefix exists', () => {
    const prefixes = [...source.matchAll(/\bt\(\s*`([\w.]+)\.\$\{/g)].map((m) => m[1])
    const missing = prefixes.filter((prefix) => ![...deKeys.keys()].some((key) => key.startsWith(`${prefix}.`)))
    expect(missing).toEqual([])
  })

  it('placeholders match between languages', () => {
    for (const [key, text] of deKeys) {
      const names = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()
      expect(names(enKeys.get(key) ?? ''), key).toEqual(names(text))
    }
  })
})
