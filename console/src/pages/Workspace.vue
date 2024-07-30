<script lang="ts" setup>
import AlertView from '@/components/AlertView.vue'
import CommonText from '@/components/CommonText.vue'
import FullPage from '@/components/FullPage.vue'
import LogEntryView from '@/components/LogEntryView.vue'
import MessageView from '@/components/MessageView.vue'
import ProcedureView from '@/components/ProcedureView.vue'
import ResizeHandle from '@/components/ResizeHandle.vue'
import { useDialogs } from '@/dialogs'
import icons from '@/icons'
import { provideWorkspaceContext, useWorkspaces } from '@/workspace'
import { QPopupEdit } from 'quasar'
import { computed } from 'vue'

const { name } = defineProps<{
  name: string
}>()

const workspaces = useWorkspaces()
const dialogs = useDialogs()
const context = provideWorkspaceContext({
  name: computed(() => name),
})

let renamePopup = $ref<QPopupEdit | null>(null)

let nameValue = $computed({
  get: () => context.name,
  set: (value: string) => {
    if (value == context.name) {
      return
    }

    const workspace = context.rename(value)
    if (workspace != null) {
      workspaces.open(workspace.name)
    }
  },
})

function promptDelete() {
  dialogs
    .delete({
      title: 'Delete Workspace',
      message: `Are you sure you want to delete workspace "${context.name}"?`,
    })
    .onOk(() => {
      context.delete()
    })
}
</script>

<template>
  <full-page>
    <template #header-append>
      <div>
        <common-text class="q-ml-md q-py-sm" variant="title2">
          {{ context.name }}
        </common-text>
        <q-popup-edit
          v-if="context.data != null"
          ref="renamePopup"
          v-slot="scope"
          v-model="nameValue"
          anchor="center left"
          auto-save
          class="no-shadow q-pa-none"
          self="center right"
          :validate="(value: string) => value.trim() !== ''"
        >
          <q-card bordered class="q-pa-sm" flat>
            <q-input
              v-model.trim="scope.value"
              dense
              filled
              label="Workspace Name"
              @keyup.enter="scope.set()"
            />
          </q-card>
        </q-popup-edit>
      </div>
      <q-btn class="q-ml-sm" flat :icon="icons.more" round size="xs">
        <q-menu anchor="top right" class="no-shadow" :offset="[8, 0]" self="top left">
          <q-list bordered>
            <q-item v-close-popup clickable dense @click="renamePopup?.show()">
              <q-item-section avatar>
                <q-icon :name="icons.rename" />
              </q-item-section>
              <q-item-section>
                <q-item-label>Rename</q-item-label>
              </q-item-section>
            </q-item>
            <q-item clickable dense @click="promptDelete">
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
    </template>
    <div class="q-pa-xs">
      <div v-if="context.data == null" class="q-py-lg text-center">
        <div>No workspace named "{{ name }}" exists. Create it?</div>
        <q-btn class="q-mt-md" color="primary" label="Create" @click="context.create" />
      </div>
      <div v-else>
        <div
          v-for="(row, i) in context.data.layout"
          :key="i"
          class="full-width q-pa-xs relative-position row"
          :style="{ height: `${row.height}px` }"
        >
          <resize-handle
            v-model="row.height"
            :class="$style.verticalResizeHandle"
            direction="vertical"
            hidden
            :min="150"
          />
          <div
            v-for="(widget, j) in row.widgets"
            :key="j"
            class="col relative-position"
            :style="j < row.widgets.length - 1 ? { width: `${widget.width}px` } : undefined"
          >
            <resize-handle
              v-model="widget.width"
              :class="$style.horizontalResizeHandle"
              direction="horizontal"
              hidden
              :min="50"
            />
            <q-card bordered class="col column full-height" flat>
              <div class="q-px-sm q-py-xs">
                <common-text class="text-capitalize" variant="th">
                  {{ widget.type }}
                </common-text>
              </div>
              <q-separator />
              <div class="col-grow overflow-auto q-pa-xs">
                <template v-if="widget.type === 'messages'">
                  <message-view class="full-height" :persist="`widget/${widget.id}`" />
                </template>
                <template v-else-if="widget.type === 'alerts'">
                  <alert-view class="full-height" :persist="`widget/${widget.id}`" />
                </template>
                <template v-else-if="widget.type === 'logs'">
                  <log-entry-view class="full-height" :persist="`widget/${widget.id}`" />
                </template>
                <template v-else-if="widget.type === 'procedures'">
                  <procedure-view :persist="`widget/${widget.id}`" />
                </template>
              </div>
            </q-card>
          </div>
        </div>
      </div>
    </div>
    <div :class="$style.bottomPadding" />
  </full-page>
</template>

<style lang="scss" module>
.verticalResizeHandle {
  position: absolute;
  left: 0;
  bottom: 4px;
  z-index: 100;
}

.horizontalResizeHandle {
  position: absolute;
  right: 0;
  top: 0px;
  z-index: 100;
}

.bottomPadding {
  height: 250px;
}
</style>
