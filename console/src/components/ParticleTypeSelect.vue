<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'

import { Address } from '@/api/address'
import { ParticleTypeInfo } from '@/api/components'
import { useEngine } from '@/api/engine'

let modelValue = $(defineModel<string | null>({ required: true }))

const { address } = defineProps<{
  address: string | null
}>()

const engine = useEngine()

// The types endpoint takes a concrete address, so a wildcard or pipe selector, which fails
// `Address`'s stricter parse, leaves the field with no declared types to offer.
const componentAddress = $computed<Address | null>(() => {
  if (address == null) {
    return null
  }

  try {
    return Address.parse(address)
  } catch {
    return null
  }
})

const query = useQuery({
  queryKey: computed(() => ['particle-types', componentAddress?.toString() ?? null]),
  queryFn: () => engine.components.getParticleTypes(componentAddress as Address),
  enabled: computed(() => componentAddress != null),
  retry: false,
})

const types = $computed<ParticleTypeInfo[]>(() => query.data.value ?? [])

const options = $computed(() =>
  types.map((type) => ({
    label: type.type,
    value: type.type,
    description: type.description,
  }))
)
</script>

<template>
  <q-select
    v-model="modelValue"
    clearable
    dense
    emit-value
    label="Particle Type"
    map-options
    new-value-mode="add-unique"
    :options
    options-dense
    outlined
    use-input
  >
    <template #option="{ itemProps, opt }">
      <q-item v-bind="itemProps" dense>
        <q-item-section>
          <q-item-label>{{ opt.label }}</q-item-label>
          <q-item-label v-if="opt.description" caption>{{ opt.description }}</q-item-label>
        </q-item-section>
      </q-item>
    </template>
  </q-select>
</template>
