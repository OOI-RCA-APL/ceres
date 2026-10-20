<script lang="ts">
export type FileNameDialogProps = {
  title: string
  /** What the field asks for, such as "Name" or "Path". */
  label: string
  /** The text the field starts with. */
  value?: string
  okLabel: string
}
</script>

<script lang="ts" setup>
const { title, label, value = '', okLabel } = defineProps<FileNameDialogProps>()

const emit = defineEmits<{ close: [string | false] }>()

let text = $ref(value)
const trimmed = $computed(() => text.trim())

function submit() {
  if (trimmed !== '' && trimmed !== value) {
    emit('close', trimmed)
  }
}
</script>

<template>
  <c-modal :title="title" @update:open="(open: boolean) => open || emit('close', false)">
    <template #body>
      <c-form-field :label="label">
        <c-input
          v-model="text"
          autofocus
          class="w-full"
          :spellcheck="false"
          @keydown.enter="submit()"
        />
      </c-form-field>
    </template>
    <template #footer>
      <div class="flex w-full items-center justify-end gap-2">
        <c-button color="neutral" variant="ghost" @click="emit('close', false)">Cancel</c-button>
        <c-button :disabled="trimmed === '' || trimmed === value" @click="submit()">
          {{ okLabel }}
        </c-button>
      </div>
    </template>
  </c-modal>
</template>
