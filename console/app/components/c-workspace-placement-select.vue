<script lang="ts" setup>
import { engineRoot } from '@/api/address'
import { useEngine } from '@/api/engine'
import icons from '@/icons'

const { current = null, disabled = false } = defineProps<{
  /** Where the workspace sits now, marked in the list. */
  current?: string | null
  disabled?: boolean
}>()

/** The chosen placement, `~` for global, null before anything is chosen. */
let value = $(defineModel<string | null>({ default: null }))

const engine = useEngine()

type Option = { label: string; value: string; icon: string; isCurrent: boolean }

// Global leads, since it is the one choice that is not a component.
const options = $computed<Option[]>(() => [
  {
    label: 'Global (None)',
    value: engineRoot,
    icon: icons.home,
    isCurrent: current === engineRoot,
  },
  ...engine.components.all.map((component) => {
    const address = component.address.toString()
    return {
      label: address,
      value: address,
      icon: icons.components,
      isCurrent: current === address,
    }
  }),
])

const selected = $computed(() => options.find((option) => option.value === value))
</script>

<template>
  <c-select-menu
    class="w-full"
    :disabled="disabled"
    :icon="selected?.icon"
    :items="options"
    :model-value="selected"
    placeholder="Choose a component"
    :search-input="{ placeholder: 'Filter...' }"
    @update:model-value="(option: Option | undefined) => (value = option?.value ?? null)"
  >
    <template #item-label="{ item }">
      {{ item.label }}
      <span v-if="item.isCurrent" class="ml-1.5 opacity-55">(Current)</span>
    </template>
  </c-select-menu>
</template>
