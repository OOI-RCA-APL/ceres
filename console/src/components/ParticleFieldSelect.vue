<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'

import { Address } from '@/api/address'
import { ParticleTypeInfo } from '@/api/components'
import { useEngine } from '@/api/engine'
import { isType, Schema } from '@/schema-form'

let modelValue = $(defineModel<string | null>({ required: true }))

const { address, particleType } = defineProps<{
  address: string | null
  particleType: string | null
}>()

const engine = useEngine()

// The types endpoint takes a concrete address, so a wildcard or pipe selector, which fails
// `Address`'s stricter parse, leaves the field with no declared fields to offer.
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

const selectedType = $computed(() => types.find((type) => type.type === particleType) ?? null)

function isPlottable(schema: Schema): boolean {
  return isType(schema, 'number') || isType(schema, 'integer')
}

function describeType(schema: Schema): string {
  for (const type of ['string', 'number', 'integer', 'boolean', 'array', 'object']) {
    if (isType(schema, type)) {
      return type
    }
  }

  return 'value'
}

// Fields that can plot lead the list, since those are the ones worth reaching for first.
const fields = $computed(() => {
  const fields = selectedType?.fields ?? []
  const plottable = fields.filter((field) => isPlottable(field.schema as Schema))
  const rest = fields.filter((field) => !isPlottable(field.schema as Schema))
  return [...plottable, ...rest]
})

const options = $computed(() =>
  fields.map((field) => {
    const schema = field.schema as Schema
    const title = typeof schema === 'object' ? schema.title : undefined
    const description = typeof schema === 'object' ? schema.description : undefined

    return {
      label: title ?? field.name,
      value: field.name,
      typeLabel: describeType(schema),
      description,
    }
  })
)
</script>

<template>
  <q-select
    v-model="modelValue"
    clearable
    dense
    emit-value
    label="Field"
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
          <q-item-label caption>
            <span class="monospace-sm">{{ opt.typeLabel }}</span>
            <span v-if="opt.description">&nbsp;&middot; {{ opt.description }}</span>
          </q-item-label>
        </q-item-section>
      </q-item>
    </template>
  </q-select>
</template>
