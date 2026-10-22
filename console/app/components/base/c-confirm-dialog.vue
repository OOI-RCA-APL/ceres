<script lang="ts">
export type ConfirmDialogProps = {
  title?: string
  message?: string
  /** Secondary consequence text shown under the message, muted. */
  note?: string
  persistent?: boolean
  okLabel?: string
  okColor?: 'primary' | 'error' | 'warning'
  cancelLabel?: string
  /** Offers a checkbox to stop asking, whose `stop` runs when the dialog is confirmed with it
  checked. Cancelling leaves things as they were. */
  stopAsking?: { label: string; stop: () => void }
  /** Text the user types before the dialog confirms, for an action nothing can undo. */
  confirmText?: string
}
</script>

<script lang="ts" setup>
const {
  title = 'Confirm',
  persistent = false,
  okLabel = 'Ok',
  okColor = 'primary',
  cancelLabel = 'Cancel',
  stopAsking,
  confirmText,
} = defineProps<ConfirmDialogProps>()

const emit = defineEmits<{ close: [boolean] }>()

let isStoppingAsking = $ref(false)
let typed = $ref('')
const isConfirmable = $computed(() => confirmText == null || typed === confirmText)

function confirm() {
  if (!isConfirmable) {
    return
  }

  if (isStoppingAsking) {
    stopAsking?.stop()
  }

  emit('close', true)
}
</script>

<template>
  <c-modal
    :description="message"
    :dismissible="!persistent"
    :title="title"
    @update:open="(value: boolean) => value || emit('close', false)"
  >
    <template v-if="note != null || confirmText != null" #body>
      <div class="flex flex-col gap-3">
        <c-text v-if="note != null" class="text-muted italic" variant="body3">{{ note }}</c-text>
        <c-form-field
          v-if="confirmText != null"
          :label="`Type &quot;${confirmText}&quot; to confirm`"
        >
          <c-input
            v-model="typed"
            autofocus
            class="w-full"
            :spellcheck="false"
            @keydown.enter="confirm()"
          />
        </c-form-field>
      </div>
    </template>
    <template #footer>
      <div class="flex w-full items-center justify-end gap-2">
        <c-checkbox
          v-if="stopAsking != null"
          v-model="isStoppingAsking"
          class="group mr-auto"
          :label="stopAsking.label"
          size="sm"
          :ui="{ label: 'opacity-70 transition-opacity duration-150 group-hover:opacity-100' }"
        />
        <c-button color="neutral" variant="ghost" @click="emit('close', false)">
          {{ cancelLabel }}
        </c-button>
        <c-button :color="okColor" :disabled="!isConfirmable" @click="confirm()">
          {{ okLabel }}
        </c-button>
      </div>
    </template>
  </c-modal>
</template>
