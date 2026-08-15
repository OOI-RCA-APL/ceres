<script lang="ts" setup>
import { startCase } from 'lodash-es'
import { watchEffect } from 'vue'

import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import icons from '@/icons'
import { isEmptyObjectSchema, useSchemaForm } from '@/schema-form'
import { deepClone } from '@/utilities'
import type { Plain } from '@/utilities'
import { ButtonStylingModel, ColorModel, useWorkspace } from '@/workspace'
import type { ButtonAction } from '@/workspace'

const { button } = defineProps<{
  button: ButtonAction
}>()

const engine = useEngine()
const workspace = useWorkspace()

const resolvedAddress = $computed(() => {
  const resolved = workspace.resolveAddress(button.address)
  return resolved == null ? null : Address.parse(resolved)
})

const component = $computed(() =>
  resolvedAddress != null ? engine.components.get(resolvedAddress) : null,
)

const possibleActions = $computed(
  () =>
    component?.procedures
      .filter((procedure) => procedure.type === 'action')
      .map((procedure) => procedure.name) ?? [],
)

watchEffect(() => {
  if (button.action != null && !possibleActions.includes(button.action)) {
    button.action = undefined
  }
})

const action = $computed(() => {
  if (resolvedAddress == null || button.action == null) {
    return null
  }

  return engine.components.getAction(resolvedAddress, button.action)
})

// The full path of what pressing runs, written the way an address is, the same as the popup's
// title. Only shown once there is an action, so the parts are there to name.
const actionPath = $computed(() => `${resolvedAddress}::actions::${button.action}`)

// The arguments the button holds, edited where the rest of it is set up rather than only from the
// popup a press opens. Written straight onto the button, since these are the arguments it offers
// next time and, locked, the ones it runs with.
const held = {
  value: () => button.arguments as Plain,
  onUpdate: (value: unknown) => {
    button.arguments = deepClone(value) as Record<string, unknown>
  },
}

const form = useSchemaForm({
  ...held,
  schema: () => action?.arguments.json_schema ?? { type: 'object', properties: {} },
  title: 'Arguments',
})

const takesArguments = $computed(() => !isEmptyObjectSchema(form.getSchema([])))
</script>

<template>
  <div class="flex flex-col gap-2">
    <!-- How the button looks comes first, and what pressing it does follows, so the action ends
    up right above the arguments it takes. -->
    <c-text variant="th">Appearance</c-text>
    <div class="grid grid-cols-2 gap-2">
      <!-- The default carries the name the button would generate for itself, so the field shows
      as a placeholder what leaving it empty means. -->
      <c-schema-form-value
        v-model="button.label"
        :schema="{
          type: 'string',
          title: 'Label',
          optional: true,
          default: button.action != null ? startCase(button.action) : undefined,
        }"
      />
      <c-schema-form-value
        v-model="button.tooltip"
        :schema="{ type: 'string', title: 'Tooltip', optional: true }"
      />
      <c-schema-form-value
        v-model="button.color"
        :schema="{ type: 'string', title: 'Color', enum: ColorModel.options, optional: true }"
      />
      <c-schema-form-value
        v-model="button.styling"
        :schema="{
          type: 'string',
          title: 'Style',
          enum: ButtonStylingModel.options,
          optional: true,
        }"
      />
    </div>
    <c-text variant="th">Action</c-text>
    <c-workspace-address-select
      :model-value="button.address?.toString() ?? null"
      @update:model-value="
        (value) => (button.address = value != null && value !== '' ? Address.parse(value) : null)
      "
    />
    <c-schema-form-value
      v-model="button.action"
      :schema="{ type: 'string', title: 'Action', enum: possibleActions, optional: true }"
    />
    <div v-if="button.action != null">
      <!-- The confirm and the lock ride the action they govern, the same controls in the same
      corner as the popup's, so the two places read as one thing. The lock only means anything
      for an action taking arguments, so only there is it offered. -->
      <div class="flex flex-nowrap items-center gap-1">
        <c-text class="grow" variant="mono-sm">{{ actionPath }}</c-text>
        <c-tooltip :text="button.confirm ? 'Confirm Dialog Enabled' : 'Confirm Dialog Disabled'">
          <c-button
            :color="button.confirm ? 'primary' : 'warning'"
            :icon="icons.confirmDialog"
            size="xs"
            variant="ghost"
            @click="button.confirm = !button.confirm"
          />
        </c-tooltip>
        <!-- Locked runs with one less look at the arguments, which is the riskier state, so it
        is the one that carries the warning color. -->
        <c-tooltip
          v-if="takesArguments"
          :text="button.locked ? 'Arguments Locked' : 'Arguments Unlocked'"
        >
          <c-button
            :color="button.locked ? 'warning' : 'primary'"
            :icon="button.locked ? icons.locked : icons.unlocked"
            size="xs"
            variant="ghost"
            @click="button.locked = !button.locked"
          />
        </c-tooltip>
      </div>
      <div v-if="takesArguments" class="border-default mt-1 rounded-md border p-2">
        <c-schema-form :form />
      </div>
    </div>
  </div>
</template>
