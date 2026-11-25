<script lang="ts" setup>
import icons from '@/icons'
import { useWorkspace } from '@/workspace'

/** A field entered by hand, for a type or field its component does not declare. */
export type ParticleManualEntry = {
  address: string
  type: string
  field: string
  connection: string | null
  label: string | null
}

const { labeled = false, chooseLabel = 'Add' } = defineProps<{
  /** Whether the entry takes a label of its own, as a chart series does. */
  labeled?: boolean

  /** What the button that takes the entry says. */
  chooseLabel?: string
}>()

const emit = defineEmits<{
  choose: [entry: ParticleManualEntry]
}>()

const workspace = useWorkspace()

let isOpen = $ref(false)
let address = $ref<string | null>(null)
let type = $ref<string | null>(null)
let field = $ref<string | null>(null)
let connection = $ref<string | null>(null)
let label = $ref('')

const resolvedAddress = $computed(() => workspace.resolveAddress(address)?.toString() ?? address)

/** Hand the entry over. The field and label clear for the next one, the source stays. */
function choose() {
  if (resolvedAddress == null || type == null || field == null) {
    return
  }

  emit('choose', {
    address: resolvedAddress,
    type,
    field,
    connection,
    label: labeled && label !== '' ? label : null,
  })
  field = null
  label = ''
}
</script>

<template>
  <!-- Collapsed by default since manual entry is the fallback for undeclared fields. -->
  <div class="border-default rounded-md border">
    <button
      class="hover:bg-elevated/50 flex w-full items-center gap-1 px-2 py-0.5 text-left"
      type="button"
      @click="isOpen = !isOpen"
    >
      <c-icon
        class="text-muted shrink-0 transition-transform"
        :class="isOpen && 'rotate-90'"
        :name="icons.chevronRight"
        size="12"
      />
      <c-text variant="title3">Manual Entry</c-text>
    </button>
    <div v-if="isOpen" class="flex flex-col gap-2 p-2 pt-3">
      <c-workspace-address-select v-model="address" />
      <c-particle-type-select v-model="type" :address="resolvedAddress" />
      <c-particle-field-select v-model="field" :address="resolvedAddress" :particle-type="type" />
      <!-- A type two connections both produce otherwise reads whichever record landed last. -->
      <c-particle-connection-select
        v-model="connection"
        :address="resolvedAddress"
        :particle-type="type"
      />
      <div class="flex items-end gap-2">
        <c-input
          v-if="labeled"
          v-model="label"
          class="flex-1"
          placeholder="Label"
          size="sm"
          spellcheck="false"
        />
        <div v-else class="flex-1" />
        <c-button
          :disabled="resolvedAddress == null || type == null || field == null"
          :label="chooseLabel"
          size="sm"
          @click="choose"
        />
      </div>
    </div>
  </div>
</template>
