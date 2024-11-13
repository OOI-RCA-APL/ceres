<script lang="ts" setup>
import RecordView from '@/components/RecordView.vue'
import SchemaFormBase from '@/components/schema-form/SchemaFormBase.vue'
import { AlertsWidget } from '@/workspace'

const { widget } = $defineProps<{
  widget: AlertsWidget
}>()

const columns = $computed(() => [
  { label: 'Level', name: 'level', filtered: widget.filter.level != null },
  {
    label: 'Type',
    name: 'type',
    filtered:
      (widget.filter.type_contains ?? widget.filter.type_prefix ?? widget.filter.type_suffix) !=
      null,
  },
  {
    label: 'Data',
    name: 'data',
    filtered:
      (widget.filter.data_contains ?? widget.filter.data_prefix ?? widget.filter.data_suffix) !=
      null,
  },
])
</script>

<template>
  <record-view :columns="columns" :filter="widget.filter" :widget>
    <template #column-filter-level>
      <div style="min-width: 200px">
        <schema-form-base
          v-model="widget.filter.level"
          :schema="{
            title: 'Level',
            type: 'string',
            enum: ['debug', 'info', 'warning', 'error', 'critical'],
            optional: true,
          }"
        />
      </div>
    </template>
    <template #column-filter-type>
      <div class="column q-gutter-xs" style="min-width: 200px">
        <schema-form-base
          v-model="widget.filter.type_contains"
          :schema="{ title: 'Contains', type: 'string', optional: true }"
        />
        <schema-form-base
          v-model="widget.filter.type_contains"
          :schema="{ title: 'Prefix', type: 'string', optional: true }"
        />
      </div>
    </template>
    <template #column-filter-data>
      <div class="column q-gutter-xs" style="min-width: 300px">
        <schema-form-base
          v-model="widget.filter.data_contains"
          :schema="{
            title: 'Contains',
            type: 'string',
            optional: true,
          }"
        />
        <schema-form-base
          v-model="widget.filter.data_prefix"
          :schema="{
            title: 'Prefix',
            type: 'string',
            optional: true,
          }"
        />
      </div>
    </template>
  </record-view>
</template>
