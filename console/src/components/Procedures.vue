<script lang="ts" setup>
import { upperFirst } from 'lodash'
import { computed, watchEffect } from 'vue'

import { ComponentInfo } from '@/api/components'
import Procedure from '@/components/Procedure.vue'
import { useInterfaceContext } from '@/interface'
import { usePersisted } from '@/persistence'

const { component, type } = defineProps<{
  component: ComponentInfo
  type: 'action' | 'query'
}>()

const context = useInterfaceContext()

const actions = $computed(() =>
  component.procedures.filter((procedure) => procedure.type === 'action')
)
const queries = $computed(() =>
  component.procedures.filter((procedure) => procedure.type === 'query')
)

const procedures = $computed(() => (type === 'action' ? actions : queries))

const persisted = usePersisted({
  schema: ({ object, string }) =>
    object({
      selectedName: string().nullable().default(null),
    }),
  methods: computed(() => [
    {
      type: 'local-storage',
      key: [context.key, 'state', 'procedures', component.address],
    },
  ]),
})

let selected = $computed(() => {
  if (persisted.selectedName == null) {
    return null
  }

  return procedures.find((procedure) => procedure.name === persisted.selectedName) ?? null
})

const typePlural = $computed(() => (type === 'action' ? 'actions' : 'queries'))

watchEffect(() => {
  if (selected == null && procedures.length > 0) {
    persisted.selectedName = procedures[0]?.name ?? null
  }
})
</script>

<template>
  <div>
    <template v-if="procedures.length">
      <div class="row">
        <div class="col">
          <q-select
            v-model="persisted.selectedName"
            class="monospace-md q-mb-sm"
            dense
            filled
            :label="upperFirst(type)"
            :options="procedures.map((procedure) => procedure.name)"
            options-dense
            popup-content-class="no-shadow monospace-md"
          />
        </div>
      </div>
      <template v-if="selected">
        <procedure :key="selected.name" :address="component.address" :procedure="selected" />
      </template>
    </template>
    <template v-else>
      <div class="items-center justify-center q-pa-sm row" :style="{ opacity: 0.5 }">
        No available {{ typePlural }} were found.
      </div>
    </template>
  </div>
</template>

<style module>
.toggle {
  opacity: 0.65;
  z-index: 1;
}

.toggle:focus-visible {
  outline: 1px solid grey;
}
</style>
