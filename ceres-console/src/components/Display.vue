<script lang="ts" setup>
import { ComponentInfo, LayoutDisplay } from '@/api/models'
import { useDisplayStream } from '@/api/operations'
import ChartDisplay from '@/components/displays/ChartDisplay.vue'
import GaugeDisplay from '@/components/displays/GaugeDisplay.vue'
import StateDisplay from '@/components/displays/StateDisplay.vue'
import ValueDisplay from '@/components/displays/ValueDisplay.vue'
import SchemaForm from '@/components/schema-form/SchemaForm.vue'
import { DisplayInfo } from '@/display'
import { createSchemaForm } from '@/schema-form'
import { QMarkupTable, QTh, QTr, debounce } from 'quasar'
import { computed, watch } from 'vue'

const { component, display } = defineProps<{
  component: ComponentInfo
  display: LayoutDisplay
}>()

let info: DisplayInfo | null = $shallowRef(null)

const procedure = $computed(
  () =>
    component.procedures.find(
      (procedure) => procedure.kind === 'query' && procedure.name === display.procedure
    ) ?? null
)

const form = procedure
  ? createSchemaForm({
      schema: computed(() => procedure.args.json_schema),
      persist: computed(() =>
        procedure
          ? `state/display/schema-form/${component.address}/procedures/${procedure.name})`
          : undefined
      ),
      inline: true,
    })
  : null

if (form && !form.isValid) {
  form.reset()
}

let args = $ref<Record<string, unknown>>(form?.value ?? ({} as any))

watch(
  () => form?.value,
  debounce(() => {
    args = form?.value ?? ({} as any)
  }, 250)
)

useDisplayStream(
  component.address,
  display.procedure,
  computed(() => args),
  (current) => {
    info = current
  }
)
</script>

<template>
  <q-card bordered class="column full-height self-display-root" flat>
    <q-markup-table dense flat separator="cell">
      <thead class="self-header">
        <q-tr no-hover>
          <q-th>{{ display.title }}</q-th>
        </q-tr>
      </thead>
    </q-markup-table>
    <div class="col-grow items-center justify-center q-pa-xs row">
      <template v-if="info">
        <value-display v-if="info.kind === 'value'" :info="info" />
        <state-display v-else-if="info.kind === 'state'" :info="info" />
        <gauge-display v-else-if="info.kind === 'gauge'" :info="info" />
        <chart-display v-else-if="info.kind === 'chart'" :info="info" />
      </template>
      <template v-else><q-spinner /></template>
    </div>
    <div v-if="form != null" class="q-mb-sm q-mx-sm">
      <schema-form :form="form" />
    </div>
  </q-card>
</template>

<style lang="scss" scoped>
.body--dark .self-display-root {
  background-color: #131313;
}

.self-header {
  background-color: $grey-1;
}

.body--dark .self-header {
  background-color: #1d1d1d;
}
</style>
