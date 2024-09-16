<script lang="ts" setup>
import Procedures from '@/components/Procedures.vue'
import { ProceduresWidget } from '@/workspace'
import { upperFirst } from 'lodash'
import { useEngine } from '@/api/engine'

const { widget } = defineProps<{
  widget: ProceduresWidget
}>()

const engine = useEngine()

const procedureComponent = $computed(() => {
  if (widget.procedureAddress == null) {
    return null
  }

  return engine.components.get(widget.procedureAddress)
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
  <procedures
    v-if="procedureComponent != null"
    :component="procedureComponent"
    :type="widget.procedureType"
  />
</template>

<style lang="scss" module>
.procedureTypeColumn {
  width: 140px;
}
</style>
