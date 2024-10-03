<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import WorkspaceAddWidgetMenu from '@/components/WorkspaceAddWidgetMenu.vue'
import WorkspaceWidgetAlerts from '@/components/WorkspaceWidgetAlerts.vue'
import WorkspaceWidgetLogs from '@/components/WorkspaceWidgetLogs.vue'
import WorkspaceWidgetMessages from '@/components/WorkspaceWidgetMessages.vue'
import WorkspaceWidgetProcedures from '@/components/WorkspaceWidgetProcedures.vue'
import WorkspaceWidgetUi from '@/components/WorkspaceWidgetUi.vue'
import icons from '@/icons'
import { useWorkspace, Widget, WidgetRow } from '@/workspace'

defineProps<{
  widget: Widget
  container: WidgetRow
  row: number
  column: number
}>()

const workspace = useWorkspace()
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
        <div>
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
        <div>
          <q-btn
            class="faded-hover q-ml-xs"
            flat
            :icon="icons.more"
            round
            size="6px"
            @mousedown.stop
            @touchstart.stop
          >
            <q-menu anchor="top right" class="no-shadow" :offset="[8, 0]" self="top left">
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
      <div class="col-grow overflow-auto q-pa-sm" style="height: 0">
        <template v-if="widget.type === 'messages'">
          <workspace-widget-messages class="full-height" :widget="widget" />
        </template>
        <template v-else-if="widget.type === 'alerts'">
          <workspace-widget-alerts class="full-height" :widget="widget" />
        </template>
        <template v-else-if="widget.type === 'logs'">
          <workspace-widget-logs class="full-height" :widget="widget" />
        </template>
        <template v-else-if="widget.type === 'procedures'">
          <workspace-widget-procedures :widget="widget" />
        </template>
        <template v-else-if="widget.type === 'ui'">
          <workspace-widget-ui :widget="widget" />
        </template>
      </div>
    </template>
  </q-card>
</template>

<style lang="scss" module>
.popupEdit {
  box-shadow: unset !important;
  padding: 0 !important;
}
</style>
