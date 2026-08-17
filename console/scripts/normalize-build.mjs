#!/usr/bin/env node
/**
 * Replace the clock readings the generator stamps into the bundle with a fixed value.
 *
 * The built bundle is committed, so a timestamp in it makes every rebuild a diff across
 * files whose content is otherwise identical.
 */
import { readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const output = fileURLToPath(new URL('../.output/public', import.meta.url))

// Nuxt compares builds by their id, so the time beside it carries nothing. One is used
// rather than zero because the prerendered payload reads its copy for truthiness, which
// decides whether a payload is served from cache.
const fixedTime = 1

const payloadTag = /(<script[^>]*id="__NUXT_DATA__"[^>]*>)(.*?)(<\/script>)/s

/** Pin the time a manifest records, leaving the id that identifies the build alone. */
function normalizeManifest(path) {
  const manifest = JSON.parse(readFileSync(path, 'utf8'))
  if (manifest.timestamp === fixedTime) {
    return false
  }

  manifest.timestamp = fixedTime
  writeFileSync(path, JSON.stringify(manifest))
  return true
}

/**
 * Pin the time a prerendered page records.
 *
 * The payload is devalue-encoded, so the number beside `prerenderedAt` is the index of the
 * slot holding the time rather than the time itself, and writing over the key would point
 * the payload at the wrong slot.
 */
function normalizePage(path) {
  const html = readFileSync(path, 'utf8')
  const tag = payloadTag.exec(html)
  if (tag == null) {
    return false
  }

  const payload = JSON.parse(tag[2])
  const slot = payload[0]?.prerenderedAt
  if (typeof slot !== 'number' || payload[slot] === fixedTime) {
    return false
  }

  payload[slot] = fixedTime
  writeFileSync(path, html.replace(payloadTag, `$1${JSON.stringify(payload)}$3`))
  return true
}

const entries = readdirSync(output, { recursive: true, withFileTypes: true })
let normalized = 0
for (const entry of entries) {
  if (!entry.isFile()) {
    continue
  }

  const path = join(entry.parentPath, entry.name)
  if (path.includes(join('_nuxt', 'builds')) && entry.name.endsWith('.json')) {
    normalized += normalizeManifest(path) ? 1 : 0
  } else if (entry.name.endsWith('.html')) {
    normalized += normalizePage(path) ? 1 : 0
  }
}

console.log(`Normalized ${normalized} generated file(s).`)
