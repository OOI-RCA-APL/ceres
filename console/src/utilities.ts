import Color from 'color'
import { throttle } from 'lodash-es'
import moment, { Duration, Moment } from 'moment'
import Prism from 'prismjs'
import { colors, debounce } from 'quasar'
import { ComputedRef, Ref, computed, isRef, shallowRef, watch } from 'vue'
import { ZodType } from 'zod'

export type Plain = string | number | boolean | null | { [property: string]: Plain } | Plain[]
export type MaybeRef<T> = Ref<T> | T
export type MaybePromise<T> = Promise<T> | T

export function jsonEquals(left: unknown, right: unknown) {
  return JSON.stringify(left) === JSON.stringify(right)
}

export function deepClone<T>(value: T) {
  return JSON.parse(JSON.stringify(value))
}

export function asRef<T>(value: MaybeRef<T>): Readonly<Ref<T>> {
  return isRef(value) ? value : computed(() => value)
}

export function hash(str: string): string {
  let result = 0
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i)
    result = (result << 5) - result + char
    result &= result
  }

  return new Uint32Array([result])[0].toString(36)
}

export function parseDuration(value: string | number | Duration): Duration {
  function getException() {
    return new Error(
      'Invalid time-delta value.' +
        'Must be a moment duration, a number, or a string number with a unit suffix ' +
        "'ms', 's', 'm', 'h', or 'd'."
    )
  }

  if (moment.isDuration(value)) {
    return value
  }

  if (typeof value === 'string' && value.trim() === '') {
    throw getException()
  }

  if (typeof value === 'number') {
    return moment.duration(value, 'seconds')
  }
  if (!Number.isNaN(Number(value))) {
    return moment.duration(Number(value), 'seconds')
  }

  if (typeof value !== 'string') {
    throw getException()
  }

  if (value.startsWith('P') && moment.duration(value).isValid()) {
    return moment.duration(value)
  }

  value = value.trim().toLowerCase()

  try {
    if (value.endsWith('ms')) {
      const decodedValue = parseFloat(value.slice(0, value.length - 2))
      return moment.duration(decodedValue, 'milliseconds')
    } else if (value.endsWith('s')) {
      const decodedValue = parseFloat(value.slice(0, value.length - 1))
      return moment.duration(decodedValue, 'seconds')
    } else if (value.endsWith('m')) {
      const decodedValue = parseFloat(value.slice(0, value.length - 1))
      return moment.duration(decodedValue, 'minutes')
    } else if (value.endsWith('h')) {
      const decodedValue = parseFloat(value.slice(0, value.length - 1))
      return moment.duration(decodedValue, 'hours')
    } else if (value.endsWith('d')) {
      const decodedValue = parseFloat(value.slice(0, value.length - 1))
      return moment.duration(decodedValue, 'days')
    }
  } catch {}

  throw getException()
}

export function displayDuration(
  value: string | Duration,
  options?: { decimals?: number; long?: boolean }
): string {
  const decimals = options?.decimals
  const long = options?.long ?? false

  const delta = moment.duration(value)
  if (delta.asMilliseconds() === 0) {
    return '0'
  }

  let unitValue, unit
  if (delta.asSeconds() < 1) {
    unitValue = delta.asMilliseconds()
    unit = long ? 'milliseconds' : 'ms'
  } else if (delta.asMinutes() < 1) {
    unitValue = delta.asSeconds()
    unit = long ? 'seconds' : 's'
  } else if (delta.asHours() < 1) {
    unitValue = delta.asMinutes()
    unit = long ? 'minutes' : 'm'
  } else if (delta.asDays() < 1) {
    unitValue = delta.asHours()
    unit = long ? 'hours' : 'h'
  } else {
    unitValue = delta.asDays()
    unit = long ? 'days' : 'd'
  }

  if (unitValue === 1 && long) {
    unit = unit.replace(/s$/, '')
  }

  let displayedValue
  if (decimals != null) {
    displayedValue = unitValue.toFixed(decimals).replace(/0+$/, '').replace(/\.$/, '')
  } else {
    displayedValue = unitValue
  }

  const isApproximate = Number(displayedValue) !== unitValue
  return `${isApproximate ? '~' : ''}${displayedValue}${long ? ' ' : ''}${unit}`
}

export function debouncedComputed<T>(factory: () => T, delay: number): ComputedRef<T> {
  const result: Ref<T> = shallowRef(factory())
  watch(
    () => factory(),
    debounce((update) => {
      result.value = update
    }, delay)
  )

  return computed(() => result.value)
}

export function throttledComputed<T>(factory: () => T, delay: number): ComputedRef<T> {
  const result: Ref<T> = shallowRef(factory())
  watch(
    () => factory(),
    throttle((update) => {
      result.value = update
    }, delay)
  )

  return computed(() => result.value)
}

export function isLight(color: string): boolean {
  const variable = colors.getPaletteColor(color)
  if (variable != null) {
    color = variable
  }

  return new Color(color).isLight()
}

export function isDark(color: string): boolean {
  return !isLight(color)
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

export type HighlightLanguage = 'json' | 'log'

export function highlight(text: string, language: HighlightLanguage): string {
  return Prism.highlight(text, Prism.languages[language], language)
}

export function safeArrayOf<T>(type: ZodType<T, any, any>, typeName?: string) {
  return type.array().catch(({ input }) => {
    const results = [] as T[]
    if (Array.isArray(input)) {
      for (const current of input) {
        const { data: parsed, error } = type.safeParse(current)
        if (error != null) {
          console.error(`Failed to parse ${typeName ?? 'object'}`, error)
        } else {
          results.push(parsed)
        }
      }
    }

    return results
  })
}
type PendingEntry<T> = {
  timestamp: Moment
  promise: Promise<T>
  waiters: number
}

export type DataloaderFunction<T> = (filter: any, options?: DataloaderOptions) => Promise<T>

export type DataloaderOptions = Partial<{
  cache: number | false // Milliseconds before pending promises are considered stale.
  key: (filter: any) => string
}>

export function dataloader<F extends DataloaderFunction<T>, T>(
  factory: F,
  { cache: defaultCache = 50, key: defaultKeyFactory = JSON.stringify }: DataloaderOptions = {}
) {
  const mapping = factory as Record<string, any>
  const pending: Map<string, PendingEntry<T>> = (mapping['__pending__'] ??= new Map())
  async function wrapper(filter: Parameters<F>[0], dataloaderOptions: DataloaderOptions = {}) {
    const cache = dataloaderOptions.cache ?? defaultCache
    if (!cache || cache <= 0) {
      return await factory(filter)
    }

    const keyFactory = dataloaderOptions.key ?? defaultKeyFactory
    const key = keyFactory(filter)
    let entry = pending.get(key)

    try {
      if (entry && entry.timestamp.isAfter(moment.utc().subtract(cache, 'ms'))) {
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
      entry = { timestamp: moment.utc(), promise, waiters: 1 }
      pending.set(key, entry)
      try {
        return await promise
      } finally {
        if (--entry.waiters === 0) {
          pending.delete(key)
        }
      }
    } finally {
      pending.delete(key)
    }
  }

  Object.defineProperty(wrapper, 'name', { value: factory.name })
  return wrapper as (
    filter: Parameters<typeof factory>[0],
    dataloaderOptions?: DataloaderOptions
  ) => Promise<T>
}
