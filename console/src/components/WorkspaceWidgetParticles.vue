<script lang="ts" setup>
import { AddressSelector } from '@/api/address'
import { useEngine } from '@/api/engine'
import RecordView from '@/components/RecordView.vue'
import SchemaFormBase from '@/components/schema-form/SchemaFormBase.vue'
import { ParticlesWidget } from '@/workspace'

const { widget } = defineProps<{
  widget: ParticlesWidget
}>()

const engine = useEngine()

const columns = $computed(() => [
  {
    label: 'Timestamp',
    name: 'timestamp',
    filtered: widget.filter.after != null || widget.filter.before != null,
  },
  { label: 'Address', name: 'address', filtered: widget.filter.address != null },
  { label: 'Type', name: 'type', filtered: widget.filter.type != null },
  { label: 'Data', name: 'data' },
])
</script>

<template>
  <record-view :columns="columns" :filter="widget.filter as any" type="particle">
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
            enum: engine.components.all.flatMap((current) => [
              current.address.toString(),
              current.address.all().toString(),
            ]),
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
    <template #column-filter-type>
      <div style="min-width: 200px">
        <schema-form-base
          v-model="widget.filter.type"
          :schema="{
            title: 'Type',
            type: 'string',
            optional: true,
          }"
        />
      </div>
    </template>
  </record-view>
</template>
