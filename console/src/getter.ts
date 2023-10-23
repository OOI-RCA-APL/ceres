import { computed, ComputedRef, ref, watch } from 'vue'

export function getter<TFunction extends (...args: any[]) => TResult, TResult>(
  dependencies: Parameters<typeof watch>[0],
  fn: TFunction
): ComputedRef<TFunction> {
  const result = ref(fn)
  watch(dependencies, () => {
    result.value = (...args: Parameters<TFunction>) => fn(...args)
  })

  return computed(() => result.value)
}
