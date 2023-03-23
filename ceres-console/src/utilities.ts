import { computed, isRef, Ref } from 'vue'

export type Plain = string | number | boolean | null | { [property: string]: Plain } | Plain[]
export type MaybeRef<T> = Ref<T> | T

export function asRef<T>(value: MaybeRef<T>): Readonly<Ref<T>> {
  return isRef(value) ? value : computed(() => value)
}

export function fromRef<T>(value: MaybeRef<T>): T {
  return isRef(value) ? value.value : value
}
