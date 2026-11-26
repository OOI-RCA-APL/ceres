<script lang="ts" setup>
import { startCase } from 'lodash-es'
import { nextTick, watch, watchEffect } from 'vue'

import { Address } from '@/api/address'
import { isButtonProcedure, procedureNamespace } from '@/api/components'
import { useEngine } from '@/api/engine'
import icons from '@/icons'
import { rememberArguments, rememberedArguments } from '@/procedure-arguments'
import { isEmptyObjectSchema, useSchemaForm } from '@/schema-form'
import { deepClone } from '@/utilities'
import type { Plain } from '@/utilities'
import { ButtonStylingModel, ColorModel, useWorkspace } from '@/workspace'
import type { ButtonWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ButtonWidget
}>()

const engine = useEngine()
const workspace = useWorkspace()

const resolvedAddress = $computed(() => {
  const resolved = workspace.resolveAddress(widget.address)
  return resolved == null ? null : Address.parse(resolved)
})

const component = $computed(() =>
  resolvedAddress != null ? engine.components.get(resolvedAddress) : null,
)

// A button shows what a query returns in a popup, which holds a value but not a file or a stream,
// so those queries are left out.
const possibleProcedures = $computed(
  () =>
    component?.procedures
      .filter((procedure) => isButtonProcedure(procedure))
      .map((procedure) => procedure.name) ?? [],
)

watchEffect(() => {
  if (widget.action != null && !possibleProcedures.includes(widget.action)) {
    widget.action = undefined
  }
})

const procedure = $computed(() => {
  if (resolvedAddress == null || widget.action == null) {
    return null
  }

  return engine.components.getProcedure(resolvedAddress, widget.action)
})

// The full path of what pressing runs, written the way an address is, the same as the popup's
// title. Only shown once there is a procedure, so the parts are there to name.
const procedurePath = $computed(
  () => `${resolvedAddress}::${procedureNamespace(procedure)}::${widget.action}`,
)

/** Choose what the button runs, asking first by default for an action but not for a query, which
only reads. Only a choice made here sets it, so a stored button keeps whatever it was given. */
function chooseProcedure(name: string | null | undefined) {
  widget.action = name ?? undefined
  if (resolvedAddress != null && name != null) {
    const chosen = engine.components.getProcedure(resolvedAddress, name)
    if (chosen != null) {
      widget.confirm = chosen.type === 'action'
    }
  }
}

// The arguments the button holds, edited where the rest of it is set up rather than only from the
// popup a press opens. Written straight onto the button, since these are the arguments it offers
// next time and, locked, the ones it runs with.
const held = {
  value: () => widget.arguments as Plain,
  onUpdate: (value: unknown) => {
    widget.arguments = deepClone(value) as Record<string, unknown>
    if (resolvedAddress != null && widget.action != null) {
      rememberArguments(resolvedAddress, widget.action, value)
    }
  },
}

const form = useSchemaForm({
  ...held,
  schema: () => procedure?.arguments.json_schema ?? { type: 'object', properties: {} },
  title: 'Arguments',
})

// Arguments belong to one procedure of one component, so pointing the button at another takes up
// what was last entered for that one, or its defaults.
watch([() => resolvedAddress?.toString(), () => widget.action], async () => {
  const remembered =
    resolvedAddress != null && widget.action != null
      ? rememberedArguments(resolvedAddress, widget.action)
      : undefined
  widget.arguments = remembered === undefined ? {} : deepClone(remembered)
  await nextTick()
  if (!form.isValid) {
    form.reset()
  }
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
        :model-value="widget.name === '' ? undefined : widget.name"
        :schema="{
          type: 'string',
          title: 'Label',
          optional: true,
          default: widget.action != null ? startCase(widget.action) : undefined,
        }"
        @update:model-value="
          (value: unknown) => (widget.name = typeof value === 'string' ? value : '')
        "
      />
      <c-schema-form-value
        v-model="widget.tooltip"
        :schema="{ type: 'string', title: 'Tooltip', optional: true }"
      />
      <c-schema-form-value
        v-model="widget.color"
        :schema="{ type: 'string', title: 'Color', enum: ColorModel.options }"
      />
      <c-schema-form-value
        v-model="widget.styling"
        :schema="{
          type: 'string',
          title: 'Style',
          enum: ButtonStylingModel.options,
          optional: true,
        }"
      />
    </div>
    <c-text variant="th">Procedure</c-text>
    <c-workspace-address-select
      :model-value="widget.address?.toString() ?? null"
      @update:model-value="
        (value) => (widget.address = value != null && value !== '' ? Address.parse(value) : null)
      "
    />
    <c-schema-form-value
      :model-value="widget.action"
      :schema="{ type: 'string', title: 'Procedure', enum: possibleProcedures, optional: true }"
      @update:model-value="(value: unknown) => chooseProcedure(value as string | null | undefined)"
    />
    <div v-if="widget.action != null">
      <!-- The confirm and the lock ride the procedure they govern, the same controls in the same
      corner as the popup's, so the two places read as one thing. The lock only means anything
      for a procedure taking arguments, so only there is it offered. -->
      <div class="flex flex-nowrap items-center gap-1">
        <c-text class="grow" variant="mono-sm">{{ procedurePath }}</c-text>
        <c-tooltip :text="widget.confirm ? 'Confirm Dialog Enabled' : 'Confirm Dialog Disabled'">
          <c-button
            :color="widget.confirm ? 'primary' : 'warning'"
            :icon="icons.confirmDialog"
            size="xs"
            variant="ghost"
            @click="widget.confirm = !widget.confirm"
          />
        </c-tooltip>
        <!-- Locked runs with one less look at the arguments, which is the riskier state, so it
        is the one that carries the warning color. -->
        <c-tooltip
          v-if="takesArguments"
          :text="widget.locked ? 'Arguments Locked' : 'Arguments Unlocked'"
        >
          <c-button
            :color="widget.locked ? 'warning' : 'primary'"
            :icon="widget.locked ? icons.locked : icons.unlocked"
            size="xs"
            variant="ghost"
            @click="widget.locked = !widget.locked"
          />
        </c-tooltip>
      </div>
      <div v-if="takesArguments" class="border-default mt-1 rounded-md border p-2">
        <c-schema-form :form />
      </div>
    </div>
  </div>
</template>
