<script lang="ts" setup>
import { watch } from 'vue'

import { useEngine } from '@/api/engine'
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
  return value.startsWith('@') && (!workspace.isBound || value !== scope.toString())
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
  }
)

type Option = { label: string; value: string; isDefault?: boolean }

const options = $computed<Option[]>(() => {
  if (!workspace.isBound || showAbsolute) {
    // The scope root is the default whichever list it is met in, so it says so here as well.
    const base = workspace.isBound ? scope.toString() : null
    return engine.components.all.map((component) => {
      const address = component.address.toString()
      return address === base
        ? { label: address, value: address, isDefault: true }
        : { label: address, value: address }
    })
  }

  const base = scope.toString()
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

function update(value: string | null) {
  emit('update:modelValue', value)
}
</script>

<template>
  <div class="items-center q-col-gutter-sm row">
    <div class="col-grow">
      <q-select
        clearable
        dense
        emit-value
        label="Component"
        map-options
        :model-value="modelValue"
        :options="options"
        options-dense
        outlined
        @update:model-value="update"
      >
        <template #option="{ itemProps, opt }">
          <q-item v-bind="itemProps" dense>
            <q-item-section>
              <q-item-label>
                <template v-if="opt.isDefault">
                  <span :class="$style.defaultAddress">{{ opt.label }}</span>
                  <span :class="$style.defaultTag">(Default)</span>
                </template>
                <template v-else>{{ opt.label }}</template>
              </q-item-label>
            </q-item-section>
          </q-item>
        </template>
        <template #selected-item="{ opt }">
          <template v-if="opt?.isDefault">
            <span :class="$style.defaultAddress">{{ opt.label }}</span>
            <span :class="$style.defaultTag">(Default)</span>
          </template>
          <template v-else>{{ typeof opt === 'string' ? opt : opt?.label }}</template>
        </template>
      </q-select>
    </div>
    <div v-if="workspace.isBound" class="col-auto">
      <q-toggle v-model="showAbsolute" dense label="Absolute" size="sm" />
    </div>
  </div>
</template>

<style lang="scss" module>
// The scope's own address is what leaving the choice alone already means, so it is shown standing
// a little back from the addresses that would actually change something.
.defaultAddress {
  opacity: 0.8;
}

.defaultTag {
  margin-left: 6px;
  opacity: 0.55;
}
</style>
