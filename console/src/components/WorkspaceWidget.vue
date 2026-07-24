<script lang="ts" setup>
import { QPopupEdit } from 'quasar'

import CommonText from '@/components/CommonText.vue'
import WorkspaceAddWidgetMenu from '@/components/WorkspaceAddWidgetMenu.vue'
import WorkspaceWidgetRestricted from '@/components/WorkspaceWidgetRestricted.vue'
import icons from '@/icons'
import { usePreferences } from '@/preferences'
import { getWidgetInfo, useWorkspace, Widget, WidgetRow } from '@/workspace'

const { widget } = defineProps<{
  widget: Widget
  container: WidgetRow
  row: number
  column: number
}>()

const workspace = useWorkspace()
const preferences = usePreferences()
const popupEdit = $ref<QPopupEdit | null>(null)

const info = $computed(() => getWidgetInfo(widget.type))
const settingsComponent = $computed(() => {
  if ('settingsComponent' in info) {
    return info.settingsComponent
  }

  return null
})

let isShowingSettingsDialog = $ref(false)
let reloads = $ref(0)

function onReloadRequested() {
  reloads++
}

function onSettingsRequested() {
  isShowingSettingsDialog = true
}

const key = $computed(() => {
  if (info.options.reloadOnThemeChange) {
    return String(preferences.isDarkModeEnabled) + '/' + String(reloads)
  }

  return String(reloads)
})

// The first address-like field on the widget resolved through the scope, or null when the
// widget has no single target.
const targetAddress = $computed(() => {
  if (widget.restricted) {
    return null
  }

  const raw =
    ('address' in widget ? widget.address : null) ??
    ('procedureAddress' in widget ? widget.procedureAddress : null) ??
    ('interfaceAddress' in widget ? widget.interfaceAddress : null) ??
    ('particleAddress' in widget ? widget.particleAddress : null)
  if (raw == null) {
    return null
  }

  const resolved = workspace.resolveAddress(raw)
  const text = resolved?.toString() ?? null
  return text != null && text.startsWith('@') && !text.includes(':') ? text : null
})
</script>

<template>
  <q-card v-if="workspace != null" bordered class="col column full-height" flat>
    <div
      :class="[$style.header, 'q-px-sm', 'q-py-xs']"
      :style="{ cursor: workspace.drag != null ? 'grabbing' : 'grab' }"
      @mousedown.prevent="workspace.drag = { widget, row, column }"
      @mousemove.prevent
      @touchmove.prevent
      @touchstart.prevent="workspace.drag = { widget, row, column }"
    >
      <div class="items-center no-wrap row">
        <div>
          <common-text :class="$style.name" variant="th" @mousedown.stop @touchstart.stop>
            {{ widget.name }}
            <q-popup-edit
              ref="popupEdit"
              v-slot="scope"
              v-model="widget.name"
              auto-save
              :class="$style.popupEdit"
              self="top left"
            >
              <q-card bordered class="q-pa-sm" flat style="max-width: 200px">
                <q-input
                  v-model.trim="scope.value"
                  autofocus
                  clearable
                  dense
                  filled
                  label="Widget Name"
                  @clear="scope.value = ''"
                  @keyup.enter="scope.set()"
                />
              </q-card>
            </q-popup-edit>
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
          >
            <q-dialog v-model="isShowingSettingsDialog">
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
          </q-btn>
        </div>
        <div>
          <q-btn
            class="faded-hover"
            flat
            :icon="icons.more"
            round
            size="7px"
            @mousedown.stop
            @touchstart.stop
          >
            <q-menu anchor="top right" :offset="[8, 0]" self="top left">
              <q-list bordered>
                <q-item v-close-popup clickable dense @click="popupEdit?.show()">
                  <q-item-section avatar>
                    <q-icon :name="icons.rename" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Rename</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item
                  v-close-popup
                  clickable
                  dense
                  @click="workspace.duplicateWidget(widget.id, row, column + 1)"
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
                  <workspace-add-widget-menu :column="column" :row="row" />
                </q-item>
                <q-item clickable dense>
                  <q-item-section avatar>
                    <q-icon :name="icons.add" />
                  </q-item-section>
                  <q-item-section>
                    <q-item-label>Add Widget After</q-item-label>
                  </q-item-section>
                  <workspace-add-widget-menu :column="column + 1" :row="row" />
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
          </q-btn>
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
      <q-separator />
      <div
        :key="key"
        :class="[$style.content, 'col-grow overflow-auto', info.options.paddingClass]"
      >
        <workspace-widget-restricted v-if="widget.restricted" :widget />
        <component
          :is="info.component as any"
          v-else
          :class="info.options.fullHeight && 'full-height'"
          :widget="widget"
          @reload-requested="onReloadRequested"
          @settings-requested="onSettingsRequested"
        />
      </div>
    </template>
  </q-card>
</template>

<style lang="scss" module>
@use 'sass:color';
:global(.light) .header {
  background-color: color.adjust(white, $lightness: -1%);
}

.name {
  cursor: text;
}

.name:hover {
  opacity: 0.6;
}

.content {
  height: 0 !important;
}

:global(.dark) .content {
  background-color: $darker;
}

.popupEdit {
  box-shadow: unset !important;
  padding: 0 !important;
}

.editDialog {
  max-width: 400px;
  width: 100%;
}
</style>
