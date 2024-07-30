<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import Procedures from '@/components/Procedures.vue'
import { usePersisted } from '@/persistence'
import { upperFirst } from 'lodash'
import { computed } from 'vue'

const { persist } = defineProps<{
  persist: string
}>()

const engine = useEngine()

const persisted = usePersisted({
  schema: ({ object, string, enum: choice }) =>
    object({
      selectedProceduresAddress: string().nullable().default(null),
      selectedProcedureType: choice(['action', 'query']).default('action'),
    }),
  methods: computed(() => [{ type: 'local-storage', key: persist }]),
})

const selectedProceduresComponent = computed(() => {
  if (persisted.selectedProceduresAddress == null) {
    return null
  }

  return engine.components.get(persisted.selectedProceduresAddress)
})
</script>

<template>
  <div class="q-col-gutter-sm row">
    <div class="col">
      <q-select
        v-model="persisted.selectedProceduresAddress"
        dense
        filled
        label="Component"
        :options="engine.components.all.map((current) => current.address.toString())"
        options-dense
      />
    </div>
    <div :class="$style.procedureTypeColumn">
      <q-select
        v-model="persisted.selectedProcedureType"
        dense
        filled
        label="Procedure Type"
        :option-label="upperFirst"
        :options="['action', 'query']"
        options-dense
      />
    </div>
  </div>
  <q-separator class="q-my-sm" />
  <procedures
    v-if="selectedProceduresComponent != null"
    :component="selectedProceduresComponent"
    :type="persisted.selectedProcedureType"
  />
</template>

<style lang="scss" module>
.procedureTypeColumn {
  width: 140px;
}
</style>
