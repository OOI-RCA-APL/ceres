<template>
  <div>
    <div>
      <common-text class="q-ml-md q-py-sm" variant="title2">Schema Form Playground</common-text>
      <q-separator />
    </div>
    <div class="column q-col-gutter-sm q-pa-sm row-lg">
      <div class="col">
        <section-card title="JSON Schema">
          <q-input
            v-model="state.schemaJson"
            autogrow
            dense
            filled
            input-class="monospace"
            square
            type="textarea"
          />
        </section-card>
      </div>
      <div class="col">
        <section-card padding="sm" title="Form">
          <schema-form v-model="state.data" :schema="schema" />
        </section-card>
      </div>
      <div class="col">
        <section-card title="Form Data">
          <q-input
            autogrow
            dense
            filled
            input-class="monospace"
            :model-value="JSON.stringify(state.data, null, 2)"
            readonly
            square
            type="textarea"
          />
        </section-card>
      </div>
    </div>
  </div>
</template>

<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import SchemaForm from '@/components/SchemaForm.vue'
import SectionCard from '@/components/SectionCard.vue'
import { usePersisted } from '@/persistence'
import Zod from 'zod'

const state = usePersisted({
  schema: ({ object }) =>
    object({
      schemaJson: Zod.string().default('{\n  "type": "object"\n}'),
      data: Zod.unknown().default(() => ({})),
    }),
  methods: [{ type: 'local-storage', key: 'state/schema-form-playground' }],
  // methods: [],
})

const schema = $computed<any>(() => {
  try {
    return JSON.parse(state.schemaJson)
  } catch {
    return undefined
  }
})
</script>
