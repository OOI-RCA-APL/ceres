<script lang="ts" setup>
import { upperFirst } from 'lodash'
import { watchEffect } from 'vue'

import { useEngine } from '@/api/engine'
import Procedure from '@/components/Procedure.vue'
import { ProceduresWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ProceduresWidget
}>()

const engine = useEngine()

const component = $computed(() => {
  if (widget.procedureAddress == null) {
    return null
  }

  return engine.components.get(widget.procedureAddress)
})

const actions = $computed(
  () => component?.procedures.filter((procedure) => procedure.type === 'action') ?? []
)
const queries = $computed(
  () => component?.procedures.filter((procedure) => procedure.type === 'query') ?? []
)

const procedures = $computed(() => (widget.procedureType === 'action' ? actions : queries))

let selected = $computed(() => {
  if (widget.procedureName == null) {
    return null
  }

  return procedures.find((procedure) => procedure.name === widget.procedureName) ?? null
})

const typePlural = $computed(() => (widget.procedureType === 'action' ? 'actions' : 'queries'))

watchEffect(() => {
  if (selected == null && procedures.length > 0) {
    widget.procedureName = procedures[0]?.name ?? null
  }
})
</script>

<template>
  <div class="q-col-gutter-sm row">
    <div class="col">
      <q-select
        v-model="widget.procedureAddress"
        dense
        filled
        label="Component"
        :options="engine.components.all.map((current) => current.address.toString())"
        options-dense
      />
    </div>
    <div :class="$style.procedureTypeColumn">
      <q-select
        v-model="widget.procedureType"
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
  <div>
    <template v-if="procedures.length">
      <div class="row">
        <div class="col">
          <q-select
            v-model="widget.procedureName"
            class="monospace-md q-mb-sm"
            dense
            filled
            :label="upperFirst(widget.procedureType)"
            :options="procedures.map((procedure) => procedure.name)"
            options-dense
            popup-content-class="no-shadow monospace-md"
          />
        </div>
      </div>
      <template v-if="selected != null && component != null">
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

<style lang="scss" module>
.procedureTypeColumn {
  width: 140px;
}
</style>
