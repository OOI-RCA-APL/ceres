<script lang="ts" setup>
import { ComponentInfo, ProcedureKindModel } from '@/api/models'
import ComponentProcedure from '@/components/ComponentProcedure.vue'
import SectionCard from '@/components/SectionCard.vue'
import icons from '@/icons'
import { usePersisted } from '@/persistence'
import { upperFirst } from 'lodash'
import { computed, watchEffect } from 'vue'

const { component } = defineProps<{
  component: ComponentInfo
}>()

const actions = $computed(() =>
  component.procedures.filter((procedure) => procedure.kind === 'action')
)
const queries = $computed(() =>
  component.procedures.filter((procedure) => procedure.kind === 'query')
)

const procedures = $computed(() => (persisted.kind === 'action' ? actions : queries))

const persisted = usePersisted({
  schema: ({ object, string }) =>
    object({
      kind: ProcedureKindModel.default('action'),
      selectedName: string().nullable().default(null),
    }),
  methods: computed(() => [
    { type: 'local-storage', key: `state/component-procedures/${component.address}` },
  ]),
})

let selected = $computed(() => {
  if (persisted.selectedName == null) {
    return null
  }

  return procedures.find((procedure) => procedure.name === persisted.selectedName) ?? null
})

function nextKind() {
  persisted.kind = persisted.kind === 'action' ? 'query' : 'action'
}

const kindPlural = $computed(() => (persisted.kind === 'action' ? 'actions' : 'queries'))

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
        :icon="persisted.kind === 'action' ? icons.switchRight : icons.switchLeft"
        :label="upperFirst(kindPlural)"
        @click.stop.prevent="nextKind"
      />
    </template>
    <template v-if="procedures.length">
      <q-select
        v-model="persisted.selectedName"
        class="monospace q-mb-sm"
        dense
        filled
        :label="upperFirst(persisted.kind)"
        :options="procedures.map((procedure) => procedure.name)"
        options-dense
        popup-content-class="no-shadow monospace"
      />
      <template v-if="selected">
        <component-procedure :key="selected.name" :component="component" :procedure="selected" />
      </template>
    </template>
    <template v-else>
      <div class="items-center justify-center q-pa-sm row" :style="{ opacity: 0.5 }">
        No available {{ kindPlural }} were found.
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
