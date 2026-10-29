<script lang="ts" setup>
import type { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import {
  describePlaybackFailure,
  type PlaybackLevel,
  playbackRequest,
  playbackSchema,
} from '@/api/exporters'
import { useDialogs } from '@/dialogs'
import { useNotify } from '@/notify'
import { useSchemaForm } from '@/schema-form'
import type { Plain } from '@/utilities'

export type PlaybackDialogProps = {
  address: Address
}

const { address } = defineProps<PlaybackDialogProps>()

/** Closes with the started playback's ID, or `false` for a cancel. */
const emit = defineEmits<{ close: [string | false] }>()

const dialogs = useDialogs()
const engine = useEngine()
const notify = useNotify()

let values: unknown = $ref({})

const form = useSchemaForm({
  value: () => values as Plain,
  onUpdate: (value: unknown) => {
    values = value
  },
  schema: () => playbackSchema(),
  showTypes: false,
  // A refusal leaves the dialog open with the range as typed, so it can be corrected and sent.
  async onSubmit(submitted: {
    after: string
    before?: string | null
    level?: PlaybackLevel
    export?: boolean
  }) {
    // A full playback runs every particle listener, actions included, for each replayed particle.
    if (submitted.level === 'full') {
      const confirmed = await new Promise<boolean>((resolve) => {
        dialogs
          .confirm({
            title: 'Full Playback',
            message: 'Every particle listener runs as if live, actions included.',
            note: 'A listener that commands hardware or stores records does so once per particle.',
          })
          .onOk(() => resolve(true))
          .onCancel(() => resolve(false))
      })
      if (!confirmed) {
        return 'editing'
      }
    }

    try {
      const id = await engine.components.startPlayback(address, playbackRequest(submitted))
      emit('close', id)
    } catch (error) {
      notify.error(describePlaybackFailure(error))
      return 'editing'
    }
  },
})
</script>

<template>
  <c-modal
    :title="`Play Back ${address}`"
    :ui="{ content: 'w-[480px] max-w-[95vw]' }"
    @update:open="(value: boolean) => value || emit('close', false)"
  >
    <template #body>
      <c-schema-form :form />
    </template>
    <template #footer>
      <c-schema-form-controls
        cancel-label="Cancel"
        class="w-full"
        execute-label="Play Back"
        :form
        @cancel="emit('close', false)"
      />
    </template>
  </c-modal>
</template>
