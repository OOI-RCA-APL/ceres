<script lang="ts" setup>
import { ComponentInfo, ProcedureTypeModel } from '@/api/models'
import ComponentProcedure from '@/components/ComponentProcedure.vue'
import SectionCard from '@/components/SectionCard.vue'
import icons from '@/icons'
import { useInterfaceContext } from '@/interface'
import { usePersisted } from '@/persistence'
import { upperFirst } from 'lodash'
import { computed, watchEffect } from 'vue'

const { component } = defineProps<{
  component: ComponentInfo
}>()

const context = useInterfaceContext()

const actions = $computed(() =>
  component.procedures.filter((procedure) => procedure.type === 'action')
)
const queries = $computed(() =>
  component.procedures.filter((procedure) => procedure.type === 'query')
)

const procedures = $computed(() => (persisted.type === 'action' ? actions : queries))

const persisted = usePersisted({
  schema: ({ object, string }) =>
    object({
      type: ProcedureTypeModel.default('action'),
      selectedName: string().nullable().default(null),
    }),
  methods: computed(() => [
    {
      type: 'local-storage',
      key: [context.key, 'state', 'component-procedures', component.address],
    },
  ]),
})

let selected = $computed(() => {
  if (persisted.selectedName == null) {
    return null
  }

  return procedures.find((procedure) => procedure.name === persisted.selectedName) ?? null
})

function nextType() {
  persisted.type = persisted.type === 'action' ? 'query' : 'action'
}

const typePlural = $computed(() => (persisted.type === 'action' ? 'actions' : 'queries'))

watchEffect(() => {
  if (selected == null && procedures.length > 0) {
    persisted.selectedName = procedures[0]?.name ?? null
  }
})
</script>

<template>
  <section-card padding="sm">
    <template #header-append>
      <q-space />
      <q-chip
        :class="[$style.toggle, 'no-shadow']"
        clickable
        color="transparent"
        dense
        :icon="persisted.type === 'action' ? icons.switchRight : icons.switchLeft"
        :label="upperFirst(typePlural)"
        @click.stop.prevent="nextType"
      />
    </template>
    <template v-if="procedures.length">
      <q-select
        v-model="persisted.selectedName"
        class="monospace-md q-mb-sm"
        dense
        filled
        :label="upperFirst(persisted.type)"
        :options="procedures.map((procedure) => procedure.name)"
        options-dense
        popup-content-class="no-shadow monospace-md"
      />
      <template v-if="selected">
        <component-procedure
          :key="selected.name"
          :address="component.address"
          :procedure="selected"
        />
      </template>
    </template>
    <template v-else>
      <div class="items-center justify-center q-pa-sm row" :style="{ opacity: 0.5 }">
        No available {{ typePlural }} were found.
      </div>
    </template>
  </section-card>
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
