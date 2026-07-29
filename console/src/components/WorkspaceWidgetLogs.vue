<script lang="ts" setup>
import { LevelModel } from '@/api/shared'
import RecordView from '@/components/RecordView.vue'
import SchemaFormValue from '@/components/schema-form/SchemaFormValue.vue'
import { LogsWidget, useWorkspace } from '@/workspace'

const { widget } = defineProps<{
  widget: LogsWidget
}>()

const workspace = useWorkspace()

const resolvedFilter = $computed(() => ({
  ...widget.filter,
  address: workspace.resolveFilterAddress(widget.filter.address),
}))

const columns = $computed(() => [
  {
    label: 'Level',
    name: 'level',
    filtered: (widget.filter.level ?? widget.filter.min_level ?? widget.filter.max_level) != null,
    minWidth: 56,
  },
  {
    label: 'Content',
    name: 'content',
    filtered: (widget.filter.contains ?? widget.filter.prefix ?? widget.filter.suffix) != null,
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
    <template #column-filter-content>
      <div style="min-width: 300px">
        <div class="q-mb-xs">
          <schema-form-value
            v-model="widget.filter.prefix"
            :schema="{ title: 'Prefix', type: 'string', optional: true }"
          />
        </div>
        <schema-form-value
          v-model="widget.filter.contains"
          :schema="{ title: 'Contains', type: 'string', optional: true }"
        />
      </div>
    </template>
  </record-view>
</template>
