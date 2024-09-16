import { inject, provide } from 'vue'

import { Address } from '@/api/address'
import { interfaceContextInjectionKey } from '@/symbols'

export type InterfacePath = ReadonlyArray<string | number>

export type InterfaceContext = Readonly<{
  key: string
}>

export function useInterfaceContext(key?: string | Address | null): InterfaceContext {
  const current = inject(interfaceContextInjectionKey, null)
  if (current == null) {
    const created = { key: key?.toString() ?? '' }
    provide(interfaceContextInjectionKey, created)
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
