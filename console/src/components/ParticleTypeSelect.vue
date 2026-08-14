<script lang="ts" setup>
import { useParticleTypes } from '@/particle-types'

let modelValue = $(defineModel<string | null>({ required: true }))

const { address } = defineProps<{
  address: string | null
}>()

const types = $(useParticleTypes(() => address).types)

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
