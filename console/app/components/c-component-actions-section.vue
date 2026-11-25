<script lang="ts" setup>
import type { Address } from '@/api/address'
import type { ActionInfo } from '@/api/components'
import { canInvokeProcedure, describeProcedurePermissions } from '@/api/components'
import type { ComponentAccessLevel } from '@/api/permissions'
import type { DetailWidgetAction } from '@/components/c-detail-widget-section.vue'
import icons from '@/icons'
import { toTitle } from '@/utilities'
import { createButtonBar, createWidget } from '@/workspace'
import type { ButtonWidget, Widget, WidgetPlacement } from '@/workspace'

const {
  address,
  actions,
  access = null,
  insertDrag = null,
  insertAt = null,
} = defineProps<{
  address: Address
  actions: ActionInfo[]

  /** The caller's access to this component, which decides what it may invoke. */
  access?: ComponentAccessLevel | null

  insertDrag?:
    ((widgets: Widget[], drop: (placement: WidgetPlacement | null) => void) => void) | null
  insertAt?: ((widgets: Widget[], placement: WidgetPlacement) => void) | null
}>()

const emit = defineEmits<{
  create: [widgets: Widget[]]
}>()

let expanded = $(defineModel<boolean>('expanded', { required: true }))

/** A button for each chosen action, side by side in one bar when there are several, which is the
arrangement a set of related actions is usually wanted in. */
function buttonFor(action: ActionInfo): ButtonWidget {
  return {
    ...(createWidget('button') as ButtonWidget),
    name: toTitle(action.name),
    address: address,
    action: action.name,
  }
}

function buttonsFor(chosen: ActionInfo[]): Widget[] {
  return chosen.length === 1 ? chosen.map(buttonFor) : [createButtonBar(chosen.map(buttonFor))]
}

const widgetActions: DetailWidgetAction<ActionInfo>[] = [
  {
    label: (chosen) => (chosen.length === 1 ? 'Create Button' : 'Create Buttons'),
    separateLabel: 'Create Separate Buttons',
    icon: icons.controls,
    combined: buttonsFor,
    separate: (chosen) => chosen.map(buttonFor),
  },
]

function nameOf(action: ActionInfo): string {
  return action.name
}

// An action the caller cannot invoke makes a button that only ever refuses.
function isBlocked(action: ActionInfo): boolean {
  return !canInvokeProcedure(action, access)
}
</script>

<template>
  <c-detail-widget-section
    v-model:expanded="expanded"
    :actions="widgetActions"
    :disabled="isBlocked"
    empty="No actions."
    :insert-at
    :insert-drag
    :items="actions"
    :key-of="nameOf"
    title="Actions"
    @create="(widgets: Widget[]) => emit('create', widgets)"
  >
    <template #row="{ item, selected }">
      <div class="grow">
        <c-text :class="selected && 'text-primary'" variant="body3">{{ item.name }}</c-text>
        <c-text variant="description">{{ describeProcedurePermissions(item) }}</c-text>
      </div>
      <c-tooltip v-if="isBlocked(item)" text="Not available with your access.">
        <c-icon class="size-4 text-muted" :name="icons.locked" />
      </c-tooltip>
    </template>
  </c-detail-widget-section>
</template>
