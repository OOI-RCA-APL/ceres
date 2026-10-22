<script lang="ts" setup>
import type { Address } from '@/api/address'
import { useEngine } from '@/api/engine'
import {
  describeExportRunFailure,
  type ExporterInfo,
  exportRunRequest,
  exportRunSchema,
} from '@/api/exporters'
import { useNotify } from '@/notify'
import { useSchemaForm } from '@/schema-form'
import type { Plain } from '@/utilities'

export type ExportRunDialogProps = {
  address: Address
  exporter: ExporterInfo
}

const { address, exporter } = defineProps<ExportRunDialogProps>()

/** Closes with the started run's ID, or `false` for a cancel. */
const emit = defineEmits<{ close: [string | false] }>()

const engine = useEngine()
const notify = useNotify()

let values: unknown = $ref({})

const form = useSchemaForm({
  value: () => values as Plain,
  onUpdate: (value: unknown) => {
    values = value
  },
  schema: () => exportRunSchema(exporter.merges),
  showTypes: false,
  // A refusal leaves the dialog open with the range as typed, so it can be corrected and sent.
  async onSubmit(submitted: { after: string; before?: string | null; replace?: boolean }) {
    try {
      const id = await engine.components.startExportRun(
        address,
        exporter.name,
        exportRunRequest(submitted, exporter.merges),
      )
      emit('close', id)
    } catch (error) {
      notify.error(describeExportRunFailure(error))
      return 'editing'
    }
  },
})
</script>

<template>
  <c-modal
    :title="`Rebuild ${exporter.name}`"
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
        execute-label="Rebuild"
        :form
        @cancel="emit('close', false)"
      />
    </template>
  </c-modal>
</template>
