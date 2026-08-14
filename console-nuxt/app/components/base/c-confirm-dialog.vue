<script lang="ts">
export type ConfirmDialogProps = {
  title?: string
  message?: string
  persistent?: boolean
  okLabel?: string
  okColor?: 'primary' | 'error' | 'warning'
  cancelLabel?: string
}
</script>

<script lang="ts" setup>
const {
  title = 'Confirm',
  persistent = false,
  okLabel = 'Ok',
  okColor = 'primary',
  cancelLabel = 'Cancel',
} = defineProps<ConfirmDialogProps>()

const emit = defineEmits<{ close: [boolean] }>()
</script>

<template>
  <c-modal :description="message" :dismissible="!persistent" :title="title">
    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <c-button color="neutral" variant="ghost" @click="emit('close', false)">
          {{ cancelLabel }}
        </c-button>
        <c-button :color="okColor" @click="emit('close', true)">{{ okLabel }}</c-button>
      </div>
    </template>
  </c-modal>
</template>
