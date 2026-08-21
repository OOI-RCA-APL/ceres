import { debounce, isEqual } from 'lodash-es'
import Prism from 'prismjs'
import { titleCase } from 'title-case'
import { type ComputedRef, type Ref, computed, shallowRef, watch } from 'vue'
import type * as z from 'zod'

import 'prismjs/components/prism-json'
import 'prismjs/components/prism-log'
import 'prismjs/components/prism-yaml'

import { type Datetime, utc } from '@/time'

export type Plain =
  string | number | boolean | null | undefined | { [property: string]: Plain } | Plain[]
export type MaybeRef<T> = Ref<T> | T
export type MaybePromise<T> = Promise<T> | T

/**
 * Return `true` if the plain object representations of the two values are deeply equal, while
 * ignoring order of object properties.
 */
export function isStructurallyEqual(left: unknown, right: unknown) {
  return isEqual(deepClone(left), deepClone(right))
}

/**
 * Deep clone a value using JSON serialization.
 */
export function deepClone<T>(value: T) {
  return JSON.parse(JSON.stringify(value))
}

/** Run `action` once the menu that asked for it has finished closing.

A menu hands focus back to its own trigger as it goes, and anything reaching for focus sooner
loses it again: a popup reads the hand-back as a click away, and a fresh field loses its caret.
*/
export function afterMenuCloses(action: () => void) {
  setTimeout(action, 150)
}

export function debouncedComputed<T>(factory: () => T, delay: number): ComputedRef<T> {
  const result: Ref<T> = shallowRef(factory())
  watch(
    () => factory(),
    debounce((update) => {
      result.value = update
    }, delay),
  )

  return computed(() => result.value)
}

export function selectFile(options?: { accept?: string; multiple: false }): Promise<File | null>
export function selectFile(options?: { accept?: string; multiple: true }): Promise<File[] | null>
export function selectFile({
  accept: contentType,
  multiple,
}: Partial<{
  accept: string
  multiple: boolean
}> = {}) {
  return new Promise<File | File[] | null>((resolve) => {
    const input: HTMLInputElement = document.createElement('input')
    input.type = 'file'
    input.multiple = multiple ?? false
    input.accept = contentType ?? '*/*'
    input.addEventListener('change', async () => {
      if (input.files == null || input.files.length === 0) {
        return null
      }

      resolve(Array.from(input.files))
    })

    input.click()
  })
}

export type HighlightLanguage = 'json' | 'log' | 'yaml'

export function highlight(text: string, language: HighlightLanguage): string {
  return Prism.highlight(text, Prism.languages[language]!, language)
}

/** An array schema that drops unparsable elements with an error log instead of failing whole. */
export function safeArrayOf<T>(type: z.ZodType<T>, typeName?: string) {
  return type.array().catch(({ input }) => {
    const results = [] as T[]
    if (Array.isArray(input)) {
      for (const current of input) {
        const { data: parsed, error } = type.safeParse(current)
        if (error != null) {
          console.error(`Failed to parse ${typeName ?? 'object'}`, error)
        } else {
          results.push(parsed as T)
        }
      }
    }

    return results
  })
}

type PendingEntry<T> = {
  timestamp: Datetime
  promise: Promise<T>
  waiters: number
}

export type DataloaderFunction<T> = (filter: any, options?: DataloaderOptions) => Promise<T>

export type DataloaderOptions = Partial<{
  cache: number | false // Milliseconds before pending promises are considered stale.
  key: (filter: any) => string
}>

/** Wrap a fetch so concurrent calls with the same filter share one in-flight promise. */
export function dataloader<F extends DataloaderFunction<T>, T>(
  factory: F,
  { cache: defaultCache = 50, key: defaultKeyFactory = JSON.stringify }: DataloaderOptions = {},
) {
  const pending = new Map<string, PendingEntry<T>>()
  async function wrapper(filter: Parameters<F>[0], dataloaderOptions: DataloaderOptions = {}) {
    const cache = dataloaderOptions.cache ?? defaultCache
    if (!cache || cache <= 0) {
      return await factory(filter)
    }

    const keyFactory = dataloaderOptions.key ?? defaultKeyFactory
    const key = keyFactory(filter)
    let entry = pending.get(key)

    if (entry && entry.timestamp.isAfter(utc().subtract(cache, 'ms'))) {
      entry.waiters++
      try {
        return await entry.promise
      } finally {
        if (--entry.waiters === 0) {
          pending.delete(key)
        }
      }
    }

    const promise = factory(filter)
    entry = { timestamp: utc(), promise, waiters: 1 }
    pending.set(key, entry)
    try {
      return await promise
    } finally {
      if (--entry.waiters === 0) {
        pending.delete(key)
      }
    }
  }

  Object.defineProperty(wrapper, 'name', { value: factory.name })
  return wrapper as (
    filter: Parameters<typeof factory>[0],
    dataloaderOptions?: DataloaderOptions,
  ) => Promise<T>
}

export function roundTo(number: number, increment: number, offset: number = 0) {
  return Math.round((number - offset) / increment) * increment + offset
}

/** Render `value` to at most `decimals` places, grouped, and without trailing zeros.

A reading that lands on a whole number reads as one, so a gauge sitting at 15568 does not pad
itself out to two places nobody asked for.
*/
export function formatNumber(value: number, decimals: number): string {
  if (!Number.isFinite(value)) {
    return String(value)
  }

  return new Intl.NumberFormat(undefined, { maximumFractionDigits: decimals }).format(value)
}

// In development the engine is reached on its own port, because the dev proxy covers
// plain HTTP but cannot upgrade websockets. Production serves same-origin.
function originUrl(protocol: string, relative: string) {
  const port = import.meta.dev
    ? `:${import.meta.env.VITE_CERES_API_PORT ?? '8080'}`
    : window.location.port !== ''
      ? ':' + window.location.port
      : ''
  return `${protocol}://${window.location.hostname}${port}${relative}`
}

export function getWebSocketUrl(relative: string) {
  return originUrl(window.location.protocol.startsWith('https') ? 'wss' : 'ws', relative)
}

export function getHttpUrl(relative: string) {
  return originUrl(window.location.protocol.startsWith('https') ? 'https' : 'http', relative)
}

export function toTitle(text: string): string {
  return titleCase(text.replace(/[-_ \t\n\r]+/g, ' '))
}

export async function copyText(text: string) {
  await navigator.clipboard.writeText(text)
}

/** Save `content` as a file download named `name`. */
export function downloadFile(name: string, content: string, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}
