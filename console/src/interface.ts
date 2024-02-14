import { Address } from '@/address'
import { InjectionKey, inject, provide } from 'vue'

export type InterfacePath = ReadonlyArray<string | number>

export type InterfaceContext = Readonly<{
  key: string
}>

const injectionKey: InjectionKey<InterfaceContext> = Symbol('interfaceContext')

export function useInterfaceContext(key?: string | Address | null): InterfaceContext {
  const current = inject(injectionKey, null)
  if (current == null) {
    const created = { key: key?.toString() ?? '' }
    provide(injectionKey, created)
    return created
  }

  if (key == null) {
    return current
  }

  return {
    ...current,
    key: current.key + '$$' + key.toString(),
  }
}
