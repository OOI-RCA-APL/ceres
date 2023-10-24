import { computed, ComputedRef, shallowRef, watch } from 'vue'

export function getter<TFunction extends (...args: any[]) => TResult, TResult>(
  dependencies: Parameters<typeof watch>[0],
  fn: TFunction
): ComputedRef<TFunction> {
  const result = shallowRef<TFunction>(fn)
  watch(dependencies, () => {
    result.value = ((...args: Parameters<TFunction>) => fn(...args)) as TFunction
  })

  return computed(() => result.value as TFunction)
}
