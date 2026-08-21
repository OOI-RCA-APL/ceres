<script lang="ts" setup>
import type { Address } from '@/api/address'
import type { ActionInfo } from '@/api/components'
import { canInvokeProcedure, describeProcedurePermissions } from '@/api/components'
import type { ComponentAccessLevel } from '@/api/permissions'
import type { DetailWidgetAction } from '@/components/c-detail-widget-section.vue'
import icons from '@/icons'
import { toTitle } from '@/utilities'
import { ButtonActionModel, createWidget } from '@/workspace'
import type { ControlsWidget, Widget, WidgetPlacement } from '@/workspace'

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

/** One bar of buttons, one per action, which is the arrangement a set of related actions is
usually wanted in. */
function controlsFor(chosen: ActionInfo[]): ControlsWidget {
  const widget = createWidget('controls') as ControlsWidget
  widget.buttons = chosen.map((action) =>
    ButtonActionModel.parse({
      label: toTitle(action.name),
      address: address.toString(),
      action: action.name,
    }),
  )
  return widget
}

const widgetActions: DetailWidgetAction<ActionInfo>[] = [
  {
    // A controls widget holds nothing but buttons today, so it is named by what it gets.
    label: (chosen) => (chosen.length === 1 ? 'Create Button' : 'Create Buttons'),
    separateLabel: 'Create Separate Controls',
    icon: icons.controls,
    combined: (chosen) => [controlsFor(chosen)],
    separate: (chosen) => chosen.map((action) => controlsFor([action])),
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
