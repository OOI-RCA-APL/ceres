import { computed, isRef, Ref } from 'vue'

export type Plain = string | number | boolean | null | { [property: string]: Plain } | Plain[]
export type MaybeRef<T> = Ref<T> | T
export type MaybePromise<T> = Promise<T> | T

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
