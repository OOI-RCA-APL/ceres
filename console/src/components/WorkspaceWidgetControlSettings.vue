<script lang="ts" setup>
import { startCase } from 'lodash-es'
import { watchEffect } from 'vue'

import { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import CommonText from '@/components/CommonText.vue'
import WorkspaceAddressSelect from '@/components/WorkspaceAddressSelect.vue'
import SchemaForm from '@/components/schema-form/SchemaForm.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import icons from '@/icons'
import { isEmptyObjectSchema, useSchemaForm } from '@/schema-form'
import { deepClone, type Plain } from '@/utilities'
import { ButtonAction, ColorModel, ButtonStylingModel, useWorkspace } from '@/workspace'

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
  resolvedAddress != null ? engine.components.get(resolvedAddress) : null
)

const possibleActions = $computed(
  () =>
    component?.procedures
      .filter((procedure) => procedure.type === 'action')
      .map((procedure) => procedure.name) ?? []
)

watchEffect(() => {
  if (button.action !== undefined) {
    if (!possibleActions.includes(button.action)) {
      button.action = undefined
    }
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
//
// Cast for the same reason the popup's form casts, since the form's value type describes any plain
// value at all and the compiler gives up walking into it.
const held = {
  value: () => button.arguments as Plain,
  onUpdate: (value: unknown) => {
    button.arguments = deepClone(value) as Record<string, unknown>
  },
}

const form = useSchemaForm({
  ...(held as any),
  schema: () => action?.arguments.json_schema ?? { type: 'object', properties: {} },
  title: 'Arguments',
})

const takesArguments = $computed(() => !isEmptyObjectSchema(form.getSchema([])))
</script>

<template>
  <div class="q-col-gutter-sm row">
    <!-- How the button looks comes first, and what pressing it does follows, so the action ends
    up right above the arguments it takes. -->
    <div class="col-12">
      <common-text variant="th">Appearance</common-text>
    </div>
    <!-- The default carries the name the button would generate for itself, so the field shows as
    a placeholder what leaving it empty means. -->
    <div class="col-sm-6 col-xs-12">
      <schema-form-value
        v-model="button.label"
        :schema="{
          type: 'string',
          title: 'Label',
          optional: true,
          default: button.action != null ? startCase(button.action) : undefined,
        }"
      />
    </div>
    <div class="col-sm-6 col-xs-12">
      <schema-form-value
        v-model="button.tooltip"
        :schema="{
          type: 'string',
          title: 'Tooltip',
          optional: true,
        }"
      />
    </div>
    <div class="col-sm-6 col-xs-12">
      <schema-form-value
        v-model="button.color"
        :schema="{
          type: 'string',
          title: 'Color',
          enum: ColorModel.options,
          optional: true,
        }"
      />
    </div>
    <div class="col-sm-6 col-xs-12">
      <schema-form-value
        v-model="button.styling"
        :schema="{
          type: 'string',
          title: 'Style',
          enum: ButtonStylingModel.options,
          optional: true,
        }"
      />
    </div>
    <div class="col-12">
      <common-text variant="th">Action</common-text>
    </div>
    <!-- The address and its "Absolute" toggle take the whole line, so the toggle is not squeezed
    against the field beside it. -->
    <div class="col-12">
      <workspace-address-select
        :model-value="button.address?.toString() ?? null"
        @update:model-value="
          (value) => (button.address = value != null && value !== '' ? Address.parse(value) : null)
        "
      />
    </div>
    <div class="col-12">
      <schema-form-value
        v-model="button.action"
        :schema="{
          type: 'string',
          title: 'Action',
          enum: possibleActions,
          optional: true,
        }"
      />
    </div>
    <div v-if="takesArguments" class="col-12">
      <!-- The confirm and the lock ride the arguments they govern, the same controls in the same
      corner as the popup's, so the two places read as one thing. -->
      <div class="items-center no-wrap row">
        <common-text class="monospace-sm" variant="th">{{ actionPath }}</common-text>
        <q-space />
        <q-btn
          :color="button.confirm ? 'primary' : 'warning'"
          dense
          flat
          :icon="icons.confirmDialog"
          round
          size="sm"
          @click="button.confirm = !button.confirm"
        >
          <q-tooltip :class="button.confirm ? 'bg-primary text-white' : 'bg-warning text-dark'">
            {{ button.confirm ? 'Confirm Dialog Enabled' : 'Confirm Dialog Disabled' }}
          </q-tooltip>
        </q-btn>
        <q-btn
          :color="button.locked ? 'primary' : 'warning'"
          dense
          flat
          :icon="button.locked ? icons.locked : icons.unlocked"
          round
          size="sm"
          @click="button.locked = !button.locked"
        >
          <q-tooltip :class="button.locked ? 'bg-primary text-white' : 'bg-warning text-dark'">
            {{ button.locked ? 'Arguments Locked' : 'Arguments Unlocked' }}
          </q-tooltip>
        </q-btn>
      </div>
      <q-card bordered class="q-mt-xs q-pa-sm" flat>
        <schema-form :form />
      </q-card>
    </div>
  </div>
</template>
