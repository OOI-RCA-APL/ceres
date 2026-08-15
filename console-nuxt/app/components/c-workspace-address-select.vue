<script lang="ts" setup>
import { watch } from 'vue'

import { useEngine } from '@/api/engine'
import icons from '@/icons'
import { useWorkspace } from '@/workspace'

const { modelValue } = defineProps<{
  modelValue: string | null
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string | null] }>()

const engine = useEngine()
const workspace = useWorkspace()

const scope = $computed(() => workspace.scope)

/** Whether `value` reads as a choice from the absolute list.

The scope's own address is stored absolute while being the relative list's default, so it belongs
to either list and never says which one is showing.
*/
function countsAsAbsolute(value: string) {
  return value.startsWith('@') && (!workspace.isBound || value !== scope?.toString())
}

// A value is absolute when it names a full address. The toggle only controls which options
// are offered, the stored string carries the choice.
let showAbsolute = $ref(modelValue != null && countsAsAbsolute(modelValue))

// Keep the toggle in sync when the stored value changes out from under us, such as when this
// component is reused across rows with different particles in the chart settings editor. A
// null value does not disagree with either toggle state, so it never overrides an explicit
// user choice.
watch(
  () => modelValue,
  (value) => {
    if (value == null) {
      return
    }

    const isAbsolute = countsAsAbsolute(value)
    if (isAbsolute !== showAbsolute) {
      showAbsolute = isAbsolute
    }
  },
)

type Option = { label: string; value: string; isDefault?: boolean }

const options = $computed<Option[]>(() => {
  const scopeBase = scope?.toString() ?? null
  if (!workspace.isBound || showAbsolute || scopeBase == null) {
    // The scope root is the default whichever list it is met in, so it says so here as well.
    const base = workspace.isBound ? scopeBase : null
    return engine.components.all.map((component) => {
      const address = component.address.toString()
      return address === base
        ? { label: address, value: address, isDefault: true }
        : { label: address, value: address }
    })
  }

  const base = scopeBase
  return engine.components.all
    .filter((component) => {
      const address = component.address.toString()
      return address === base || address.startsWith(`${base}.`)
    })
    .map((component) => {
      const address = component.address.toString()
      if (address === base) {
        // The scope root itself has no relative path, so represent it with its absolute
        // address instead of an empty string, which cannot round-trip through the adopters'
        // falsy checks or `Address.parse`.
        return { label: address, value: address, isDefault: true }
      }

      return { label: address.slice(base.length + 1), value: address.slice(base.length + 1) }
    })
})

const selected = $computed(() => options.find((option) => option.value === modelValue))
</script>

<template>
  <div class="flex items-center gap-2">
    <div class="min-w-0 grow">
      <c-text class="text-muted mb-1" variant="mono-sm">Component</c-text>
      <c-select-menu
        class="w-full"
        :items="options"
        :model-value="selected"
        placeholder="Component"
        :search-input="{ placeholder: 'Filter...' }"
        size="sm"
        @update:model-value="
          (option: Option | undefined) => emit('update:modelValue', option?.value ?? null)
        "
      >
        <template #item-label="{ item }">
          <template v-if="item.isDefault">
            <span class="opacity-80">{{ item.label }}</span>
            <span class="ml-1.5 opacity-55">(Default)</span>
          </template>
          <template v-else>{{ item.label }}</template>
        </template>
        <template #trailing>
          <c-button
            v-if="modelValue != null"
            color="neutral"
            :icon="icons.clear"
            size="xs"
            square
            variant="ghost"
            @click.stop="emit('update:modelValue', null)"
          />
        </template>
      </c-select-menu>
    </div>
    <div v-if="workspace.isBound" class="shrink-0 self-end pb-1">
      <c-switch v-model="showAbsolute" label="Absolute" size="sm" />
    </div>
  </div>
</template>
