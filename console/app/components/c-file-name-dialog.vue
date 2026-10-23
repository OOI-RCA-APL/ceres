<script lang="ts">
export type FileNameDialogProps = {
  title: string
  /** What the field asks for, such as "Name". */
  label: string
  /** The text the field starts with. */
  value?: string
  /** Where the selection the field starts with ends, all of `value` when omitted. */
  selectionEnd?: number
  okLabel: string
}
</script>

<script lang="ts" setup>
import { fileNameProblem } from '@/api/files'

const { title, label, value = '', selectionEnd, okLabel } = defineProps<FileNameDialogProps>()

const emit = defineEmits<{ close: [string | false] }>()

let text = $ref(value)
let touched = $ref(false)
const trimmed = $computed(() => text.trim())
const problem = $computed(() => fileNameProblem(text))

// The modal focuses the field once it opens, so the selection is set on that first focus.
let selected = false
function selectOnce(event: FocusEvent) {
  if (!selected && event.target instanceof HTMLInputElement) {
    selected = true
    event.target.setSelectionRange(0, selectionEnd ?? value.length)
  }
}

const unchanged = $computed(() => value !== '' && trimmed === value)

// An unchanged name closes as a cancel, since there is nothing to do.
function submit() {
  touched = true
  if (unchanged) {
    emit('close', false)
  } else if (problem == null) {
    emit('close', trimmed)
  }
}
</script>

<template>
  <c-modal :title="title" @update:open="(open: boolean) => open || emit('close', false)">
    <template #body>
      <c-form-field :error="touched ? (problem ?? undefined) : undefined" :label="label">
        <c-input
          v-model="text"
          autofocus
          class="w-full"
          :spellcheck="false"
          @focus="selectOnce"
          @keydown.enter="submit()"
          @update:model-value="touched = true"
        />
      </c-form-field>
    </template>
    <template #footer>
      <div class="flex w-full items-center justify-end gap-2">
        <c-button color="neutral" variant="ghost" @click="emit('close', false)">Cancel</c-button>
        <c-button :disabled="problem != null || unchanged" @click="submit()">
          {{ okLabel }}
        </c-button>
      </div>
    </template>
  </c-modal>
</template>
