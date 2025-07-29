<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import WorkspaceAddWidgetMenu from '@/components/WorkspaceAddWidgetMenu.vue'
import WorkspaceWidgetAlerts from '@/components/WorkspaceWidgetAlerts.vue'
import WorkspaceWidgetChart from '@/components/WorkspaceWidgetChart.vue'
import WorkspaceWidgetChartEdit from '@/components/WorkspaceWidgetChartEdit.vue'
import WorkspaceWidgetLogs from '@/components/WorkspaceWidgetLogs.vue'
import WorkspaceWidgetMessages from '@/components/WorkspaceWidgetMessages.vue'
import WorkspaceWidgetParticles from '@/components/WorkspaceWidgetParticles.vue'
import WorkspaceWidgetProcedures from '@/components/WorkspaceWidgetProcedures.vue'
import WorkspaceWidgetUi from '@/components/WorkspaceWidgetUi.vue'
import WorkspaceWidgetValue from '@/components/WorkspaceWidgetValue.vue'
import WorkspaceWidgetValueEdit from '@/components/WorkspaceWidgetValueEdit.vue'
import icons from '@/icons'
import { usePreferences } from '@/preferences'
import { widgetInfos, useWorkspace, Widget, WidgetRow } from '@/workspace'

defineProps<{
  widget: Widget
  container: WidgetRow
  row: number
  column: number
}>()

const workspace = useWorkspace()
const preferences = usePreferences()

const darkModeKey = $computed(() => String(preferences.isDarkModeEnabled))

let isShowingEditDialog = $ref(false)
</script>

<template>
  <q-card v-if="workspace != null" bordered class="col column full-height" flat>
    <div
      class="q-px-sm q-py-xs"
      :style="{ cursor: workspace.drag != null ? 'grabbing' : 'grab' }"
      @mousedown.prevent="workspace.drag = { widget, row, column }"
      @mousemove.prevent
      @touchmove.prevent
      @touchstart.prevent="workspace.drag = { widget, row, column }"
    >
      <div class="items-center row">
        <div class="q-mr-xs">
          <common-text
            class="text-capitalize"
            style="cursor: text"
            variant="th"
            @mousedown.stop
            @touchstart.stop
          >
            {{ widget.name }}
            <q-popup-edit
              v-slot="scope"
              v-model="widget.name"
              auto-save
              :class="$style.popupEdit"
              self="top left"
              :validate="(value: string) => value.trim() !== ''"
            >
              <q-card bordered class="q-pa-sm" flat style="max-width: 200px">
                <q-input
                  v-model.trim="scope.value"
                  autofocus
                  dense
                  filled
                  label="Widget Name"
                  @keyup.enter="scope.set()"
                />
              </q-card>
            </q-popup-edit>
          </common-text>
        </div>
        <div v-if="widget.type === 'chart' || widget.type === 'value'">
          <q-btn
            class="faded-hover"
            flat
            :icon="icons.settings"
            round
            size="6px"
            @click.stop="isShowingEditDialog = true"
            @mousedown.stop
            @touchstart.stop
          >
            <q-dialog v-model="isShowingEditDialog">
              <q-card bordered :class="$style.editDialog" flat outline>
                <workspace-widget-chart-edit v-if="widget.type === 'chart'" :widget="widget" />
                <workspace-widget-value-edit v-if="widget.type === 'value'" :widget="widget" />

                <q-separator />
                <q-btn
                  class="full-width"
                  color="primary"
                  dense
                  flat
                  label="Done"
                  @click="isShowingEditDialog = false"
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
            size="6px"
            @mousedown.stop
            @touchstart.stop
          >
            <q-menu anchor="top right" :offset="[8, 0]" self="top left">
              <q-list bordered>
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
                  <workspace-add-widget-menu :column="column - 1" :row="row" />
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
        <q-space />
        <q-btn
          flat
          round
          size="6px"
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
        :class="['col-grow overflow-auto', widgetInfos[widget.type].paddingClass]"
        style="height: 0"
      >
        <workspace-widget-messages
          v-if="widget.type === 'messages'"
          class="full-height"
          :widget="widget"
        />
        <workspace-widget-particles
          v-else-if="widget.type === 'particles'"
          class="full-height"
          :widget="widget"
        />
        <workspace-widget-alerts
          v-else-if="widget.type === 'alerts'"
          class="full-height"
          :widget="widget"
        />
        <workspace-widget-logs
          v-else-if="widget.type === 'logs'"
          class="full-height"
          :widget="widget"
        />
        <workspace-widget-procedures v-else-if="widget.type === 'procedures'" :widget="widget" />
        <workspace-widget-ui v-else-if="widget.type === 'ui'" :widget="widget" />
        <workspace-widget-chart
          v-else-if="widget.type === 'chart'"
          :key="darkModeKey"
          class="full-height"
          :widget="widget"
        />
        <workspace-widget-value
          v-else-if="widget.type === 'value'"
          class="full-height"
          :widget="widget"
        />
      </div>
    </template>
  </q-card>
</template>

<style lang="scss" module>
.popupEdit {
  box-shadow: unset !important;
  padding: 0 !important;
}

.editDialog {
  max-width: 400px;
  width: 100%;
}
</style>
