<script lang="ts" setup>
import { AddressSelector } from '@/api/address'
import { useEngine } from '@/api/engine'
import RecordView from '@/components/RecordView.vue'
import SchemaFormBase from '@/components/schema-form/SchemaFormBase.vue'
import { LogsWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: LogsWidget
}>()

const engine = useEngine()

const columns = $computed(() => [
  {
    label: 'Timestamp',
    name: 'timestamp',
    filtered: widget.filter.after != null || widget.filter.before != null,
  },
  { label: 'Address', name: 'address', filtered: widget.filter.address != null },
  { label: 'Level', name: 'level', filtered: widget.filter.level != null },
  {
    label: 'Content',
    name: 'content',
    filtered: widget.filter.content_prefix != null || widget.filter.content_contains != null,
  },
])
</script>

<template>
  <record-view :columns="columns" :filter="widget.filter as any" type="log-entry">
    <template #column-filter-timestamp>
      <div style="min-width: 200px">
        <div class="q-mb-xs">
          <schema-form-base
            v-model="widget.filter.after"
            :schema="{ title: 'After', type: 'string', format: 'date-time', optional: true }"
          />
        </div>
        <div>
          <schema-form-base
            v-model="widget.filter.before"
            :schema="{ title: 'Before', type: 'string', format: 'date-time', optional: true }"
          />
        </div>
      </div>
    </template>
    <template #column-filter-address>
      <div style="min-width: 200px">
        <schema-form-base
          :model-value="widget.filter.address?.toString()"
          :schema="{
            title: 'Address',
            type: 'string',
            enum: ['~'].concat(
              engine.components.all.flatMap((current) => [
                current.address.toString(),
                current.address.all().toString(),
              ])
            ),
            optional: true,
          }"
          @update:model-value="
            (value) =>
              (widget.filter.address =
                value == null ? undefined : new AddressSelector(String(value)))
          "
        />
      </div>
    </template>
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
    <template #column-filter-content>
      <div style="min-width: 300px">
        <div class="q-mb-xs">
          <schema-form-base
            v-model="widget.filter.content_prefix"
            :schema="{ title: 'Prefix', type: 'string', optional: true }"
          />
        </div>
        <schema-form-base
          v-model="widget.filter.content_contains"
          :schema="{ title: 'Contains', type: 'string', optional: true }"
        />
      </div>
    </template>
  </record-view>
</template>
