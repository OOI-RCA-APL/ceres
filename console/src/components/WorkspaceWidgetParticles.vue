<script lang="ts" setup>
import RecordView from '@/components/RecordView.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import { ParticlesWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ParticlesWidget
}>()

const columns = $computed(() => [
  {
    label: 'Type',
    name: 'type',
    filtered:
      (widget.filter.type ??
        widget.filter.type_contains ??
        widget.filter.type_prefix ??
        widget.filter.type_suffix) != null,
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
  <record-view :columns="columns" :filter="widget.filter" :widget>
    <template #column-filter-type>
      <div class="column q-gutter-xs" style="min-width: 200px">
        <schema-form-value
          v-model="widget.filter.type_contains"
          :schema="{
            title: 'Contains',
            type: 'string',
            optional: true,
          }"
        />
        <schema-form-value
          v-model="widget.filter.type_prefix"
          :schema="{
            title: 'Prefix',
            type: 'string',
            optional: true,
          }"
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
