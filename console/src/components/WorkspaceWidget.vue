<script lang="ts" setup>
import { QMenu } from 'quasar'
import { watch } from 'vue'

import CommonText from '@/components/CommonText.vue'
import InlineNameEdit from '@/components/InlineNameEdit.vue'
import WorkspaceAddWidgetMenu from '@/components/WorkspaceAddWidgetMenu.vue'
import WorkspaceWidgetGroupDialog from '@/components/WorkspaceWidgetGroupDialog.vue'
import WorkspaceWidgetRestricted from '@/components/WorkspaceWidgetRestricted.vue'
import icons from '@/icons'
import { usePreferences } from '@/preferences'
import {
  convertedPagesWidget,
  createWidget,
  getWidgetInfo,
  useWorkspace,
  widgetTargetSelector,
  widgetTargetSignature,
  Widget,
  WidgetRow,
} from '@/workspace'

const { widget, layoutId } = defineProps<{
  widget: Widget
  container: WidgetRow
  row: number
  column: number

  /** The layout this widget sits in, which is what its row and column are counted against. */
  layoutId: string
}>()

const workspace = useWorkspace()
const preferences = usePreferences()

// Renaming is reached deliberately, by double-clicking the name or from the widget's menu, since a
// single press on the header is what picks the widget out and takes hold of it.
let isEditingName = $ref(false)

const info = $computed(() => getWidgetInfo(widget.type))
const settingsComponent = $computed(() => {
  if ('settingsComponent' in info) {
    return info.settingsComponent
  }

  return null
})

let isShowingSettingsDialog = $ref(false)
let isShowingGroupDialog = $ref(false)
let reloads = $ref(0)

// Held so the dots can open the same menu a right click does, at wherever the pointer is.
const menu = $ref<QMenu | null>(null)

function onReloadRequested() {
  reloads++
}

function onSettingsRequested() {
  isShowingSettingsDialog = true
}

/** The same pages the other way about, for a widget that holds pages, or null for one that does
not. Offered from the header as well as from the strip itself, since it is a change to the widget
rather than to what is on any one of its pages. */
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

// Grouping acts on everything picked out when this widget is among them, the same way dragging
// does, and on this widget alone otherwise.
const groupTargets = $computed(() =>
  workspace.isSelected(widget.id) && workspace.selectionLayout === layoutId
    ? [...workspace.selection]
    : [widget.id]
)

// Hand the widget back as one of its kind with nothing set on it, which is what a stub already is
// once it stops standing in for what it was hiding.
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
// only changes what is picked out, since a selection is built up one press at a time. Otherwise it
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

// A restricted stub loads with its address fields redacted, so the user could not have set
// them knowingly. Once the user repoints the widget to a new target, the stub is stale and its
// lock placeholder should give way to a fresh, editable widget.
const targetSignature = $computed(() => widgetTargetSignature(widget))
watch(
  () => targetSignature,
  () => {
    if (widget.restricted) {
      widget.restricted = false
    }
  }
)
</script>

<template>
  <q-card
    v-if="workspace != null"
    :bordered="!widget.frameless"
    class="col column full-height"
    :class="[
      workspace.isSelected(widget.id) && $style.selected,
      widget.frameless && $style.frameless,
    ]"
    flat
  >
    <!-- A widget wearing no frame is still taken hold of and still answers to a menu, so what the
    header carried comes up over its own corner while the pointer is on it. -->
    <div
      v-if="widget.frameless"
      :class="$style.handle"
      data-widget-header
      :style="{ cursor: workspace.drag != null ? 'grabbing' : 'grab' }"
      @mousedown.prevent="onPress"
      @mousemove.prevent
      @touchmove.prevent
      @touchstart.prevent="onPress"
    >
      <q-icon :name="icons.dragVertical" size="14px" />
      <q-btn
        flat
        :icon="icons.more"
        round
        size="7px"
        @click.stop="menu?.show($event)"
        @mousedown.stop
        @touchstart.stop
      />
    </div>
    <div
      v-else
      :class="[$style.header, 'q-px-sm', 'q-py-xs']"
      data-widget-header
      :style="{ cursor: workspace.drag != null ? 'grabbing' : 'grab' }"
      @mousedown.prevent="onPress"
      @mousemove.prevent
      @touchmove.prevent
      @touchstart.prevent="onPress"
    >
      <div class="items-center no-wrap row">
        <div>
          <common-text
            :class="[$style.name, isEditingName && $style.editingName]"
            variant="th"
            @click.shift.stop="isEditingName = true"
            @dblclick.stop="isEditingName = true"
          >
            <inline-name-edit
              v-model:editing="isEditingName"
              :name="widget.name"
              @rename="(value: string) => (widget.name = value)"
            />
          </common-text>
        </div>
        <div v-if="settingsComponent != null">
          <q-btn
            :class="['faded-hover', widget.name !== '' && 'q-ml-xs']"
            flat
            :icon="icons.settings"
            round
            size="7px"
            @click.stop="isShowingSettingsDialog = true"
            @mousedown.stop
            @touchstart.stop
          />
        </div>
        <div>
          <q-btn
            :class="['faded-hover', widget.name !== '' && 'q-ml-xs']"
            flat
            :icon="icons.more"
            round
            size="7px"
            @click="menu?.show($event)"
            @mousedown.stop
            @touchstart.stop
          />
        </div>
        <q-btn
          v-if="targetAddress != null"
          dense
          flat
          :icon="icons.chevronRight"
          round
          size="xs"
          :to="`/components/${targetAddress}`"
          @mousedown.stop
          @touchstart.stop
        >
          <q-tooltip>Open {{ targetAddress }}</q-tooltip>
        </q-btn>
        <q-space />
        <q-btn
          v-if="$q.screen.gt.xs"
          class="faded-hover"
          flat
          round
          size="7px"
          @click.prevent="onReloadRequested"
          @mousedown.stop
          @touchstart.stop
        >
          <q-icon :name="icons.refresh" size="12px" />
        </q-btn>
        <q-btn
          flat
          round
          size="7px"
          @click.prevent="container.collapsed = !container.collapsed"
          @mousedown.stop
          @touchstart.stop
        >
          <q-icon :name="container.collapsed ? icons.menuDown : icons.menuUp" size="12px" />
        </q-btn>
      </div>
    </div>
    <template v-if="!container.collapsed">
      <q-separator v-if="!widget.frameless" />
      <!-- Padded only where there is a frame to pad it away from. A widget wearing none stands on
      the layout itself, so it takes the whole of the space the frame would have taken rather than
      sitting inset inside a box that is no longer drawn. -->
      <div
        :key="key"
        :class="[
          $style.content,
          'col-grow overflow-auto',
          !widget.frameless && info.options.paddingClass,
        ]"
      >
        <workspace-widget-restricted v-if="widget.restricted" :widget />
        <component
          :is="info.component as any"
          v-else
          :class="(info.options.fullHeight || widget.frameless) && 'full-height'"
          :container="container"
          :widget="widget"
          @reload-requested="onReloadRequested"
          @settings-requested="onSettingsRequested"
        />
      </div>
    </template>
    <!-- One menu, opened by the dots or by right-clicking the widget itself, which is where a
    context menu is looked for first. Hung off the card so the whole widget answers to it. -->
    <q-menu ref="menu" context-menu>
      <q-list bordered>
        <q-item v-close-popup clickable dense @click="isEditingName = true">
          <q-item-section avatar>
            <q-icon :name="icons.rename" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Rename</q-item-label>
          </q-item-section>
        </q-item>
        <!-- A widget the viewer may not see loads with its configuration stripped, and most kinds
        of widget are configured on the widget itself, which is exactly what is hidden. This is the
        way back to one, and it gives up what it could not show in the first place. -->
        <q-item v-if="widget.restricted" v-close-popup clickable dense @click="onResetRequested">
          <q-item-section avatar>
            <q-icon :name="icons.discard" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Reset Widget</q-item-label>
          </q-item-section>
        </q-item>
        <q-item
          v-if="settingsComponent != null"
          v-close-popup
          clickable
          dense
          @click="isShowingSettingsDialog = true"
        >
          <q-item-section avatar>
            <q-icon :name="icons.settings" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Settings...</q-item-label>
          </q-item-section>
        </q-item>
        <q-item
          v-close-popup
          clickable
          dense
          @click="workspace.duplicateWidget(widget.id, row, column + 1, layoutId)"
        >
          <q-item-section avatar>
            <q-icon :name="icons.duplicate" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Duplicate</q-item-label>
          </q-item-section>
        </q-item>
        <q-separator />
        <q-item clickable dense>
          <q-item-section avatar>
            <q-icon :name="icons.add" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Add Widget Before</q-item-label>
          </q-item-section>
          <workspace-add-widget-menu :column="column" :layout-id="layoutId" :row="row" />
        </q-item>
        <q-item clickable dense>
          <q-item-section avatar>
            <q-icon :name="icons.add" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Add Widget After</q-item-label>
          </q-item-section>
          <workspace-add-widget-menu :column="column + 1" :layout-id="layoutId" :row="row" />
        </q-item>
        <q-item
          v-if="conversion != null"
          v-close-popup
          clickable
          dense
          @click="workspace.replaceWidget(widget.id, conversion.widget)"
        >
          <q-item-section avatar>
            <q-icon :name="conversion.icon" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ conversion.label }}</q-item-label>
          </q-item-section>
        </q-item>
        <!-- Grouping puts the widget, or everything picked out with it, onto the pages of a fresh
        tabs or carousel widget standing in its place. Which kind and how the pages are dealt are
        ironed out in the dialog. -->
        <q-item v-close-popup clickable dense @click="isShowingGroupDialog = true">
          <q-item-section avatar>
            <q-icon :name="icons.groupWidgets" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Group...</q-item-label>
          </q-item-section>
        </q-item>
        <!-- The inverse, for a widget that holds pages. Their rows come out onto the layout where
        the widget stands, and the widget itself goes away. -->
        <q-item
          v-if="conversion != null"
          v-close-popup
          clickable
          dense
          @click="workspace.ungroupWidget(widget.id)"
        >
          <q-item-section avatar>
            <q-icon :name="icons.ungroupWidgets" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Ungroup</q-item-label>
          </q-item-section>
        </q-item>
        <q-separator />
        <!-- Held here as well as on the header, since a widget wearing no frame has no header to
        reach either of them from. -->
        <q-item v-close-popup clickable dense @click="widget.frameless = !widget.frameless">
          <q-item-section avatar>
            <q-icon :name="widget.frameless ? icons.frame : icons.frameless" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ widget.frameless ? 'Show Frame' : 'Hide Frame' }}</q-item-label>
          </q-item-section>
        </q-item>
        <q-item v-close-popup clickable dense @click="onReloadRequested">
          <q-item-section avatar>
            <q-icon :name="icons.refresh" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Reload</q-item-label>
          </q-item-section>
        </q-item>
        <q-separator />
        <q-item v-close-popup clickable dense @click="workspace.deleteWidget(widget.id)">
          <q-item-section avatar>
            <q-icon :name="icons.delete" />
          </q-item-section>
          <q-item-section>
            <q-item-label>Delete</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-menu>
    <!-- Mounted only while showing, so its remembered choices are read fresh each time. -->
    <workspace-widget-group-dialog
      v-if="isShowingGroupDialog"
      :widget-ids="groupTargets"
      @close="isShowingGroupDialog = false"
    />
    <!-- Hung off the card rather than off the button that opens it, so the menu can open it too on
    a widget that is wearing no header. -->
    <q-dialog v-if="settingsComponent != null" v-model="isShowingSettingsDialog">
      <q-card bordered :class="$style.editDialog" flat outline>
        <component :is="settingsComponent as any" :widget="widget" />
        <q-separator />
        <q-btn
          class="full-width"
          color="primary"
          dense
          flat
          label="Done"
          @click="isShowingSettingsDialog = false"
        />
      </q-card>
    </q-dialog>
  </q-card>
</template>

<style lang="scss" module>
@use 'sass:color';

// The header is what a widget is dragged by, so a touch that starts on it is a drag rather than
// the page being scrolled.
.header {
  touch-action: none;
}

// Nothing of the card is drawn, so what the widget shows is all there is of it and it sits on the
// layout rather than in a box on it.
.frameless {
  background-color: transparent;
}

// The handle stands in for the header on a widget that wears none, over the widget's own corner so
// it costs no room, and only while the pointer is on the widget.
.handle {
  position: absolute;
  top: 0;
  right: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 1px 2px;
  border-radius: 0 0 0 4px;
  opacity: 0;
  touch-action: none;
  transition: opacity 0.15s;

  // Out of reach while it is out of sight, so a tap on a widget's top-right corner reaches the
  // widget rather than a handle nothing on a touchscreen ever showed.
  pointer-events: none;
}

.frameless:hover .handle {
  opacity: 0.85;
  pointer-events: auto;
}

.handle:hover {
  opacity: 1 !important;
}

:global(.light) .handle {
  background-color: color.adjust(white, $lightness: -4%);
}

:global(.dark) .handle {
  background-color: $dark;
}

// Drawn outside the card's own border rather than in place of it, so picking a widget out does not
// nudge everything inside it by a pixel.
.selected {
  outline: 2px solid $primary;
  outline-offset: -1px;
}

:global(.light) .header {
  background-color: color.adjust(white, $lightness: -1%);
}

.name {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

// A name being edited is not truncated, since the ellipsis that keeps a header tidy would clip the
// text being typed and the caret with it. The field grows with what is typed.
.editingName {
  max-width: none;
  overflow: visible;
}

// The box a widget is drawn in takes the card's size rather than its own contents', in both
// directions. Left to itself it grows to whatever it is holding, and something wide inside it, a
// long strip of tabs most of all, pushes the widget out past the column it was given and drags the
// whole row wider. Being told its width is what makes the box scroll instead.
.content {
  height: 0 !important;
  width: 100%;
}

:global(.dark) .content {
  background-color: $darker;
}

:global(.dark) .frameless .content {
  background-color: transparent;
}

.editDialog {
  max-width: 400px;
  width: 100%;
}
</style>
