<script lang="ts"></script>

<script lang="ts" setup>
import icons from '@/icons'
import type { Workspace } from '@/workspace'
export type WorkspaceTransferDialogProps = {
  workspace: Workspace
  /** Which side of the list the workspace was dropped on. */
  to: 'shared' | 'private'
  /** Whether the original may be moved rather than only copied, which takes manage. */
  canMove: boolean
}

const { workspace, to, canMove } = defineProps<WorkspaceTransferDialogProps>()

/** Closes with the chosen mode, or `false` for a cancel. */
const emit = defineEmits<{ close: ['copy' | 'move' | false] }>()

// Copying is the default, because it is the answer that cannot cost anyone anything. Moving is
// the same click away for whoever means it.
let mode = $ref<'copy' | 'move'>('copy')

const placement = $computed(() => workspace.scope.toString())
</script>

<template>
  <c-modal
    :title="to === 'shared' ? 'Share Workspace' : 'Make Workspace Private'"
    :ui="{ content: 'w-[520px] max-w-[95vw]' }"
    @update:open="(value: boolean) => value || emit('close', false)"
  >
    <template #body>
      <c-text class="block" variant="body1">
        <template v-if="to === 'shared'">
          "{{ workspace.name }}" becomes visible to everyone who can view
          <c-text element="span" variant="mono-xs">{{ placement }}</c-text
          >.
        </template>
        <template v-else>"{{ workspace.name }}" becomes private to you.</template>
      </c-text>

      <c-text v-if="to === 'shared'" class="mt-1 mb-4 block" variant="description">
        Anyone who can manage
        <c-text element="span" variant="mono-xs">{{ placement }}</c-text>
        can edit it.
      </c-text>

      <c-text v-else class="mt-1 mb-4 block italic text-warning" variant="body2">
        Anyone else who can see
        <c-text element="span" variant="mono-xs">{{ placement }}</c-text>
        loses access to it, along with any unsaved changes they are holding against it. Copying
        leaves the shared workspace where it is.
      </c-text>

      <c-radio-group
        v-model="mode"
        :items="[
          { label: 'Copy, leaving the original where it is.', value: 'copy' },
          { label: 'Move it.', value: 'move', disabled: !canMove },
        ]"
      />
      <c-text v-if="!canMove" class="mt-2 block pl-2" variant="description">
        Moving the original requires manage access on
        <c-text element="span" variant="mono-xs">{{ placement }}</c-text
        >.
      </c-text>
    </template>
    <template #footer>
      <div class="flex w-full gap-2">
        <c-button
          block
          class="flex-1"
          color="neutral"
          :icon="icons.cancel"
          label="Cancel"
          variant="soft"
          @click="emit('close', false)"
        />
        <c-button
          block
          class="flex-1"
          :color="mode === 'move' && to === 'private' ? 'warning' : 'primary'"
          :icon="icons.confirm"
          :label="mode === 'copy' ? 'Copy' : 'Move'"
          @click="emit('close', mode)"
        />
      </div>
    </template>
  </c-modal>
</template>
