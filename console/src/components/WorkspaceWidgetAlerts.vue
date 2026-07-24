<script lang="ts" setup>
import { LevelModel } from '@/api/shared'
import RecordView from '@/components/RecordView.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import { AlertsWidget, useWorkspace } from '@/workspace'

const { widget } = defineProps<{
  widget: AlertsWidget
}>()

const workspace = useWorkspace()

const resolvedFilter = $computed(() => ({
  ...widget.filter,
  address: workspace.resolveAddress(widget.filter.address),
}))

const columns = $computed(() => [
  {
    label: 'Level',
    name: 'level',
    filtered: (widget.filter.level ?? widget.filter.min_level ?? widget.filter.max_level) != null,
    minWidth: 56,
  },
  {
    label: 'Type',
    name: 'type',
    filtered:
      (widget.filter.type_contains ?? widget.filter.type_prefix ?? widget.filter.type_suffix) !=
      null,
    minWidth: 52,
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
  <record-view :columns="columns" :filter="resolvedFilter" :widget>
    <template #column-filter-level>
      <div style="min-width: 280px">
        <div class="q-col-gutter-xs row">
          <div class="col">
            <schema-form-value
              v-model="widget.filter.min_level"
              :schema="{
                title: 'Min',
                type: 'string',
                enum: LevelModel.options,
                optional: true,
              }"
            />
          </div>
          <div class="col">
            <schema-form-value
              v-model="widget.filter.max_level"
              :schema="{
                title: 'Max',
                type: 'string',
                enum: LevelModel.options,
                optional: true,
              }"
            />
          </div>
        </div>
      </div>
    </template>
    <template #column-filter-type>
      <div class="column q-gutter-xs" style="min-width: 200px">
        <schema-form-value
          v-model="widget.filter.type_contains"
          :schema="{ title: 'Contains', type: 'string', optional: true }"
        />
        <schema-form-value
          v-model="widget.filter.type_contains"
          :schema="{ title: 'Prefix', type: 'string', optional: true }"
        />
      </div>
    </template>
    <template #column-filter-data>
      <div class="column q-gutter-xs" style="min-width: 300px">
        <schema-form-value
          v-model="widget.filter.data_contains"
          :schema="{
            title: 'Contains',
            type: 'string',
            optional: true,
          }"
        />
        <schema-form-value
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
