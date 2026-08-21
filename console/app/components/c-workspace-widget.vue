<script lang="ts" setup>
import type { DropdownMenuItem } from '@nuxt/ui'
import { watch } from 'vue'

import icons from '@/icons'
import { useNavigation } from '@/navigation'
import { usePreferences } from '@/preferences'
import { keepFocusWhile } from '@/utilities'
import {
  convertedPagesWidget,
  createWidget,
  getWidgetInfo,
  useWorkspace,
  type Widget,
  widgetInfos,
  type WidgetRow,
  widgetTargetSelector,
  widgetTargetSignature,
} from '@/workspace'

const { widget, container, row, column, layoutId } = defineProps<{
  widget: Widget
  container: WidgetRow
  row: number
  column: number

  /** The layout this widget sits in, which its row and column are counted against. */
  layoutId: string
}>()

const navigation = useNavigation()
const workspace = useWorkspace()
const preferences = usePreferences()

let isEditingName = $ref(false)

// Hovering the name turns it into a field there and then, and clicking into it is what makes the
// offer a real edit. The rest of the header stays the widget's drag handle.
let isNameHovered = $ref(false)
const isNameOffered = $computed(() => isEditingName || isNameHovered)

// A menu closing hands focus back to whatever opened it, which would take the caret straight out
// of the field the menu's own rename just opened.
const menuContent = keepFocusWhile(() => isEditingName)

const info = $computed(() => getWidgetInfo(widget.type))
const settingsComponent = $computed(() => {
  if ('settingsComponent' in info) {
    return info.settingsComponent
  }

  return null
})

let isShowingSettingsDialog = $ref(false)
let isShowingGroupDialog = $ref(false)

// Bumped through the workspace so a reload asked of a selection reaches every widget in it.
const reloads = $computed(() => workspace.reloadStamp(widget.id))

function onReloadRequested() {
  workspace.requestReload(menuTargets)
}

function onSettingsRequested() {
  isShowingSettingsDialog = true
}

/** The widget's pages under the other pages-widget kind, or null for a widget without pages.
Offered from the header as well as from the strip itself because it changes the widget rather
than any one of its pages. */
const conversion = $computed(() => {
  const converted = convertedPagesWidget(widget)
  if (converted == null) {
    return null
  }

  return {
    widget: converted,
    label: converted.type === 'tabs' ? 'Convert To Tabs' : 'Convert To Carousel',
    icon: converted.type === 'tabs' ? icons.tab : icons.carousel,
  }
})

// The menu acts on everything picked out when this widget is among them, the same way
// dragging does, and on this widget alone otherwise. Actions that only make sense for one
// widget hide behind `actsOnMany` instead.
const menuTargets = $computed(() =>
  workspace.isSelected(widget.id) && workspace.selectionLayout === layoutId
    ? [...workspace.selection]
    : [widget.id],
)

const actsOnMany = $computed(() => menuTargets.length > 1)

/** Toggle every targeted widget's frame to where this one is headed, so a mixed selection
settles on one state rather than each widget flipping its own. */
function toggleFrames() {
  const value = !widget.frameless
  for (const id of menuTargets) {
    const target = workspace.getWidget(id)
    if (target != null) {
      target.frameless = value
    }
  }
}

// Replace the widget with a fresh one of its kind, which is all a stub is once it no longer
// hides anything.
function onResetRequested() {
  workspace.replaceWidget(widget.id, createWidget(widget.type))
}

const key = $computed(() => {
  if (info.options.reloadOnThemeChange) {
    return String(preferences.isDarkModeEnabled) + '/' + String(reloads)
  }

  return String(reloads)
})

// The address of the one component the widget is a view of, resolved through the scope, or null
// when it is a view of none.
const targetAddress = $computed(() => {
  const raw = widgetTargetSelector(widget)
  if (raw == null) {
    return null
  }

  const resolved = workspace.resolveAddress(raw)
  const text = resolved?.toString() ?? null
  return text != null && text.startsWith('@') && !text.includes(':') ? text : null
})

// A press on the header either picks the widget out or takes hold of it. Held with a modifier it
// only changes what is picked out since a selection is built up one press at a time. Otherwise it
// takes hold of everything picked out, which is just this widget unless it was already among them.
function onPress(event: MouseEvent | TouchEvent) {
  // Only the primary button arranges anything. A right press is asking the widget a question, and
  // the menu it opens is the answer.
  if ('button' in event && event.button !== 0) {
    return
  }

  if ('metaKey' in event && (event.metaKey || event.ctrlKey)) {
    workspace.selectWidget(widget.id, 'toggle', layoutId)
    return
  }
  if ('shiftKey' in event && event.shiftKey) {
    workspace.selectWidget(widget.id, 'extend', layoutId)
    return
  }

  if (!workspace.isSelected(widget.id) || workspace.selectionLayout !== layoutId) {
    workspace.selectWidget(widget.id, 'replace', layoutId)
  }

  workspace.drag = { widget, widgets: [...workspace.selectedWidgets], layout: layoutId }
}

// A restricted stub loads with its address fields redacted so the user could not have set
// them knowingly. Once the user repoints the widget to a new target, the stub is stale and its
// lock placeholder should give way to a fresh, editable widget.
const targetSignature = $computed(() => widgetTargetSignature(widget))
watch(
  () => targetSignature,
  () => {
    if (widget.restricted) {
      widget.restricted = false
    }
  },
)

type MenuItem = DropdownMenuItem

function addWidgetItems(atColumn: number): MenuItem[] {
  return Object.values(widgetInfos).map((kind) => ({
    label: kind.name,
    onSelect: () => {
      workspace.addWidget(kind.type, row, atColumn, layoutId)
    },
  }))
}

/** The widget's menu, one definition serving the dots dropdown and the right-click context
menu. */
const menuItems = $computed<MenuItem[][]>(() => {
  const single: MenuItem[] = []
  if (!actsOnMany) {
    single.push({ label: 'Rename', icon: icons.rename, onSelect: () => (isEditingName = true) })
  }
  if (!actsOnMany && targetAddress != null) {
    single.push({
      label: `Open ${targetAddress}`,
      icon: icons.chevronRight,
      onSelect: () => void navigation.push(`/components/${targetAddress}`),
    })
  }

  // A widget the viewer may not see loads with its configuration stripped, and most kinds of
  // widget are configured on the widget itself, which is exactly what is hidden. This is the way
  // back to one, and it gives up what it could not show in the first place.
  if (widget.restricted) {
    single.push({ label: 'Reset Widget', icon: icons.discard, onSelect: onResetRequested })
  }
  if (settingsComponent != null) {
    single.push({
      label: 'Settings ...',
      icon: icons.settings,
      onSelect: () => (isShowingSettingsDialog = true),
    })
  }
  single.push({
    label: 'Duplicate',
    icon: icons.duplicate,
    onSelect: () => workspace.duplicateWidgets(menuTargets),
  })

  const arranging: MenuItem[] = []
  if (!actsOnMany) {
    arranging.push(
      { label: 'Add Widget Before', icon: icons.add, children: addWidgetItems(column) },
      { label: 'Add Widget After', icon: icons.add, children: addWidgetItems(column + 1) },
    )
  }
  if (conversion != null) {
    const converted = conversion
    arranging.push({
      label: converted.label,
      icon: converted.icon,
      onSelect: () => workspace.replaceWidget(widget.id, converted.widget),
    })
  }

  // Grouping puts the widget, or everything picked out with it, onto the pages of a fresh tabs
  // or carousel widget standing in its place. Which kind and how the pages are dealt are ironed
  // out in the dialog. Ungrouping is the inverse, for a widget that holds pages.
  arranging.push({
    label: 'Group ...',
    icon: icons.groupWidgets,
    onSelect: () => (isShowingGroupDialog = true),
  })
  if (conversion != null) {
    arranging.push({
      label: 'Ungroup',
      icon: icons.ungroupWidgets,
      onSelect: () => workspace.ungroupWidget(widget.id),
    })
  }

  // Frames are held here as well as on the header since a widget wearing no frame has no header
  // to reach them from.
  const framing: MenuItem[] = [
    {
      label: `${widget.frameless ? 'Show' : 'Hide'} ${actsOnMany ? 'Frames' : 'Frame'}`,
      icon: widget.frameless ? icons.frame : icons.frameless,
      onSelect: toggleFrames,
    },
    { label: 'Reload', icon: icons.refresh, onSelect: onReloadRequested },
  ]

  return [
    [...single, ...arranging],
    framing,
    [{ label: 'Delete', icon: icons.delete, onSelect: () => workspace.deleteWidgets(menuTargets) }],
  ]
})
</script>

<template>
  <c-context-menu :content="menuContent" :items="menuItems">
    <div
      class="relative flex h-full flex-col overflow-hidden rounded-lg"
      :class="[
        !widget.frameless && 'border border-default bg-elevated',
        widget.frameless && 'group/frameless',
        // Outside the card's own border rather than in place of it, so picking a widget out does
        // not nudge everything inside it by a pixel.
        workspace.isSelected(widget.id) && 'outline-2 outline-offset-[-1px] outline-primary',
      ]"
      :data-widget-id="widget.id"
    >
      <!-- A widget wearing no frame is still taken hold of and still answers to a menu so what
      the header carried comes up over its own corner while the pointer is on it. -->
      <div
        v-if="widget.frameless"
        :class="[
          'bg-elevated absolute top-0 right-0 z-2 flex items-center gap-0.5 rounded-bl px-0.5',
          'py-px opacity-0 transition-opacity duration-150 touch-none',
          // Out of reach while out of sight, so a tap on a widget's top-right corner reaches the
          // widget rather than a handle nothing on a touchscreen ever showed.
          'pointer-events-none group-hover/frameless:pointer-events-auto',
          'group-hover/frameless:opacity-85 hover:opacity-100!',
        ]"
        data-widget-header
        :style="{ cursor: workspace.drag != null ? 'grabbing' : 'grab' }"
        @mousedown.prevent="onPress"
        @mousemove.prevent
        @touchmove.prevent
        @touchstart.prevent="onPress"
      >
        <c-icon :name="icons.dragVertical" size="14" />
        <c-dropdown-menu :content="menuContent" :items="menuItems">
          <button
            class="flex items-center rounded-full p-0.5 opacity-60 hover:opacity-100"
            type="button"
            @click.stop
            @mousedown.stop
            @touchstart.stop
          >
            <c-icon :name="icons.more" size="13" />
          </button>
        </c-dropdown-menu>
      </div>
      <div
        v-else
        class="touch-none bg-elevated px-2 py-1"
        data-widget-header
        :style="{ cursor: workspace.drag != null ? 'grabbing' : 'grab' }"
        @mousedown.prevent="onPress"
        @mousemove.prevent
        @touchmove.prevent
        @touchstart.prevent="onPress"
      >
        <div class="flex flex-nowrap items-center">
          <c-text
            :class="
              isNameOffered
                ? 'max-w-none overflow-visible'
                : 'max-w-60 overflow-hidden text-ellipsis whitespace-nowrap'
            "
            variant="th"
            @pointerenter="isNameHovered = true"
            @pointerleave="isNameHovered = false"
          >
            <c-inline-name-edit
              :claim="isEditingName"
              :editing="isNameOffered"
              :name="widget.name"
              @rename="(value: string) => (widget.name = value)"
              @update:editing="(value: boolean) => (isEditingName = value)"
            />
          </c-text>
          <button
            v-if="settingsComponent != null"
            class="flex items-center rounded-full p-0.5 opacity-60 hover:opacity-100"
            :class="widget.name !== '' && 'ml-1'"
            type="button"
            @click.stop="isShowingSettingsDialog = true"
            @mousedown.stop
            @touchstart.stop
          >
            <c-icon :name="icons.settings" size="13" />
          </button>
          <c-dropdown-menu :content="menuContent" :items="menuItems">
            <!-- No margin after the gear, whose own padding already matches the name gap. -->
            <button
              class="flex items-center rounded-full p-0.5 opacity-60 hover:opacity-100"
              :class="widget.name !== '' && settingsComponent == null && 'ml-1'"
              type="button"
              @click.stop
              @mousedown.stop
              @touchstart.stop
            >
              <c-icon :name="icons.more" size="13" />
            </button>
          </c-dropdown-menu>
          <div class="flex-1" />
          <button
            class="flex items-center rounded-full p-0.5 opacity-60 hover:opacity-100"
            type="button"
            @click.prevent="onReloadRequested"
            @mousedown.stop
            @touchstart.stop
          >
            <c-icon :name="icons.refresh" size="12" />
          </button>
          <button
            class="flex items-center rounded-full p-0.5 opacity-60 hover:opacity-100"
            type="button"
            @click.prevent="container.collapsed = !container.collapsed"
            @mousedown.stop
            @touchstart.stop
          >
            <c-icon :name="container.collapsed ? icons.menuDown : icons.menuUp" size="12" />
          </button>
        </div>
      </div>
      <template v-if="!container.collapsed">
        <c-separator v-if="!widget.frameless" />
        <!-- Padded only where there is a frame to pad it away from. A widget wearing none stands
        on the layout itself so it takes the whole of the space the frame would have taken rather
        than sitting inset inside a box that is no longer drawn. -->
        <div
          :key="key"
          :class="[
            // The box takes the card's size rather than its own contents', in both directions.
            // Left to itself it grows to whatever it holds, and something wide inside, a long
            // strip of tabs most of all, drags the whole row wider instead of scrolling.
            'h-0! w-full',
            'grow overflow-auto',
            !widget.frameless && 'bg-default',
            !widget.frameless && info.options.paddingClass,
          ]"
        >
          <c-workspace-widget-restricted v-if="widget.restricted" :widget />
          <component
            :is="info.component as any"
            v-else
            :class="(info.options.fullHeight || widget.frameless) && 'h-full'"
            :container="container"
            :widget="widget"
            @reload-requested="onReloadRequested"
            @settings-requested="onSettingsRequested"
          />
        </div>
      </template>
      <!-- Mounted only while showing so its remembered choices are read fresh each time. -->
      <c-workspace-widget-group-dialog
        v-if="isShowingGroupDialog"
        :widget-ids="menuTargets"
        @close="isShowingGroupDialog = false"
      />
      <!-- Hung off the card rather than off the button that opens it so the menu can open it too
      on a widget that is wearing no header. -->
      <c-modal v-if="settingsComponent != null" v-model:open="isShowingSettingsDialog">
        <template #content>
          <!-- Held to the viewport with the body scrolling inside it, so a long settings form
          stays reachable and "Done" stays on screen rather than below the fold. -->
          <div class="flex max-h-[85vh] flex-col">
            <div class="min-h-0 flex-1 overflow-y-auto">
              <component :is="settingsComponent as any" :widget="widget" />
            </div>
            <c-separator />
            <c-button
              block
              color="primary"
              label="Done"
              variant="ghost"
              @click="isShowingSettingsDialog = false"
            />
          </div>
        </template>
      </c-modal>
    </div>
  </c-context-menu>
</template>
