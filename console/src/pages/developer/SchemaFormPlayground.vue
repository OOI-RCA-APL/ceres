<script lang="ts" setup>
import { computed } from 'vue'
import Zod from 'zod'

import CommonText from '@/components/CommonText.vue'
import SectionCard from '@/components/SectionCard.vue'
import SchemaForm from '@/components/schema-form/SchemaForm.vue'
import { usePersisted } from '@/persistence'
import { useSchemaForm } from '@/schema-form'

const state = usePersisted({
  schema: ({ object }) =>
    object({
      schemaJson: Zod.string().default(() => JSON.stringify(createDefaultSchema(), null, 2)),
    }),
  methods: [{ type: 'local-storage', key: ['state', 'schema-form-playground', 'schema'] }],
})

const schema = $computed<any>(() => {
  try {
    return JSON.parse(state.schemaJson)
  } catch {
    return undefined
  }
})

const form = useSchemaForm({
  schema: computed(() => schema),
  persist: ['state', 'schema-form-playground', 'form'],
})

function createDefaultSchema() {
  return {
    type: 'object',
    properties: {
      name: {
        type: 'string',
        title: 'Name',
      },
      age: {
        type: 'number',
        title: 'Age',
      },
    },
  }
}
</script>

<template>
  <div>
    <div>
      <common-text class="q-ml-md q-py-sm" variant="title2">Schema Form Playground</common-text>
      <q-separator />
    </div>
    <div class="column q-col-gutter-sm q-pa-sm row-lg">
      <div class="col">
        <section-card title="Schema">
          <q-input
            v-model="state.schemaJson"
            autogrow
            dense
            filled
            input-class="monospace-sm"
            square
            type="textarea"
          />
        </section-card>
      </div>
      <div class="col">
        <section-card padding="sm" title="Form">
          <schema-form :form />
        </section-card>
      </div>
      <div class="col">
        <section-card title="Form Data">
          <q-input
            autogrow
            dense
            filled
            input-class="monospace-sm"
            :model-value="JSON.stringify(form.value, null, 2)"
            readonly
            square
            type="textarea"
          />
        </section-card>
      </div>
    </div>
  </div>
</template>
