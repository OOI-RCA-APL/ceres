<script lang="ts" setup>
import { useDialogPluginComponent } from 'quasar'
import { ref } from 'vue'

import CommonText from '@/components/CommonText.vue'
import icons from '@/icons'
import { Workspace } from '@/workspace'

const { workspace, to, canMove } = defineProps<{
  workspace: Workspace
  /** Which side of the list the workspace was dropped on. */
  to: 'shared' | 'private'
  /** Whether the original may be moved rather than only copied, which takes manage. */
  canMove: boolean
}>()

defineEmits([...useDialogPluginComponent.emits])

const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } = useDialogPluginComponent()

// Copying is the default, because it is the answer that cannot cost anyone anything. Moving is the
// same click away for whoever means it.
const mode = ref<'copy' | 'move'>('copy')

const placement = $computed(() => workspace.scope.toString())

function submit() {
  onDialogOK(mode.value)
}
</script>

<template>
  <q-dialog ref="dialogRef" @hide="onDialogHide">
    <q-card bordered class="q-dialog-plugin" :class="$style.card" flat>
      <div class="q-px-md row">
        <common-text class="q-mb-sm q-mt-sm" element="h2" variant="title1">
          {{ to === 'shared' ? 'Share Workspace' : 'Make Workspace Private' }}
        </common-text>
        <q-space />
        <div class="items-center row">
          <q-btn flat :icon="icons.close" round size="10px" @click="onDialogCancel" />
        </div>
      </div>
      <q-separator />
      <div class="q-pa-md">
        <div class="q-mb-md">
          <template v-if="to === 'shared'">
            <q-icon class="q-mr-xs" :name="icons.workspace" />
            "{{ workspace.name }}" becomes visible to everyone who can view
            <span class="monospace-xs">{{ placement }}</span
            >, and editable by anyone who can manage it.
          </template>
          <template v-else>
            <q-icon class="q-mr-xs" color="warning" :name="icons.privateWorkspace" />
            "{{ workspace.name }}" becomes private to you.
          </template>
        </div>

        <div v-if="to === 'private'" class="q-mb-md text-warning">
          <i>
            Anyone else who can see <span class="monospace-xs">{{ placement }}</span> loses access
            to it, along with any unsaved changes they are holding against it. Copying leaves the
            shared workspace where it is.
          </i>
        </div>

        <q-option-group
          v-model="mode"
          :class="$style.modes"
          color="primary"
          dense
          :options="[
            { label: 'Copy, leaving the original where it is.', value: 'copy' },
            { label: 'Move it.', value: 'move', disable: !canMove },
          ]"
        />
        <div v-if="!canMove" class="q-mt-sm q-pl-sm text-grey-6">
          Moving the original requires manage access on
          <span class="monospace-xs">{{ placement }}</span
          >.
        </div>
      </div>
      <div class="q-col-gutter-x-sm q-pb-md q-px-md row">
        <div class="col">
          <q-btn
            class="full-width"
            color="grey-8"
            :icon="icons.cancel"
            label="Cancel"
            unelevated
            @click="onDialogCancel"
          />
        </div>
        <div class="col">
          <q-btn
            class="full-width"
            :color="mode === 'move' && to === 'private' ? 'warning' : 'primary'"
            :icon="icons.confirm"
            :label="mode === 'copy' ? 'Copy' : 'Move'"
            unelevated
            @click="submit"
          />
        </div>
      </div>
    </q-card>
  </q-dialog>
</template>

<style lang="scss" module>
.card {
  max-width: 520px;
  width: 520px;
}

.modes > div + div {
  margin-top: 4px;
}
</style>
