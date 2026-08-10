import { useQuery } from '@tanstack/vue-query'
import { computed, MaybeRefOrGetter, toValue } from 'vue'

import { Address } from '@/api/address'
import { ParticleTypeInfo } from '@/api/components'
import { useEngine } from '@/api/engine'

/** Declared particle types for a component address.

The types endpoint takes a concrete address, so a wildcard or pipe selector, which fails
`Address`'s stricter parse, leaves the query disabled and `types` empty.
*/
export function useParticleTypes(address: MaybeRefOrGetter<string | null>) {
  const engine = useEngine()

  const componentAddress = computed<Address | null>(() => {
    const value = toValue(address)
    if (value == null) {
      return null
    }

    try {
      return Address.parse(value)
    } catch {
      return null
    }
  })

  const query = useQuery({
    queryKey: computed(() => ['particle-types', componentAddress.value?.toString() ?? null]),
    queryFn: () => engine.components.getParticleTypes(componentAddress.value as Address),
    enabled: computed(() => componentAddress.value != null),
    retry: false,
  })

  const types = computed<ParticleTypeInfo[]>(() => query.data.value ?? [])

  return { types }
}
