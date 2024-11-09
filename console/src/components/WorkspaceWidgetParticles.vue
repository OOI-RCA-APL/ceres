<script lang="ts" setup>
import { AddressSelector } from '@/api/address'
import { useEngine } from '@/api/engine'
import RecordView from '@/components/RecordView.vue'
import SchemaFormBase from '@/components/schema-form/SchemaFormBase.vue'
import { ParticlesWidget } from '@/workspace'

const { widget } = $defineProps<{
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
  {
    label: 'Type',
    name: 'type',
    filtered:
      (widget.filter.type ??
        widget.filter.type_contains ??
        widget.filter.type_prefix ??
        widget.filter.type_suffix) != null,
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
      <div class="column q-gutter-xs" style="min-width: 200px">
        <schema-form-base
          v-model="widget.filter.type_contains"
          :schema="{
            title: 'Contains',
            type: 'string',
            optional: true,
          }"
        />
        <schema-form-base
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
