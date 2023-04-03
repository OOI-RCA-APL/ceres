<script lang="ts" setup>
import { ComponentInfo, ProcedureInfo } from '@/api/models'
import { call } from '@/api/operations'
import SchemaForm from '@/components/schema-form/SchemaForm.vue'
import SchemaFormControls from '@/components/schema-form/SchemaFormControls.vue'
import icons from '@/icons'
import { createSchemaForm } from '@/schema-form'
import { computed } from 'vue'

const { component, procedure } = defineProps<{
  component: ComponentInfo
  procedure: ProcedureInfo
}>()

let result = $ref<any>(undefined)

const form = createSchemaForm({
  persist: computed(
    () => `state/component-procedure/${component.address}/procedures/${procedure.name})`
  ),
  schema: computed(() => procedure.args.json_schema),
  async onSubmit(value) {
    result = await call(component.address, procedure.name, value)
  },
})
</script>

<template>
  <schema-form :key="procedure.name" :form="form" />
  <schema-form-controls v-if="form" :form="form" />
  <q-card bordered class="q-mt-sm" flat title="Result">
    <div v-if="result === undefined" class="q-pa-sm text-center" style="opacity: 0.5">
      Results will be displayed here.
    </div>
    <q-input
      v-else
      autogrow
      dense
      filled
      input-class="monospace"
      :model-value="JSON.stringify(result, null, 2)"
      :rows="2"
      type="textarea"
    >
      <template #append>
        <q-btn
          v-if="result !== undefined"
          class="faded-clickable"
          dense
          flat
          :icon="icons.cancel"
          round
          @click.stop="result = undefined"
        />
      </template>
    </q-input>
  </q-card>
</template>
