<script lang="ts" setup>
import { Address, AddressSelector } from '@/api/address'
import { useEngine } from '@/api/engine'
import RecordView from '@/components/RecordView.vue'
import SchemaFormBase from '@/components/schema-form/SchemaFormBase.vue'
import { KeyInput, usePersisted } from '@/persistence'
import { computed } from 'vue'

const { address, persist } = defineProps<{
  containerClass?: string | null
  address?: Address | null
  persist?: KeyInput
}>()

const engine = useEngine()

const persisted = usePersisted({
  schema: ({ object, string }) =>
    object({
      filter: object({
        after: string().optional(),
        before: string().optional(),
        address: string().transform(AddressSelector.parse).optional(),
        level: string().optional(),
        content_prefix: string().optional(),
        content_contains: string().optional(),
      }).default(() => ({})),
    }),
  methods: computed(() => (persist ? [{ type: 'local-storage', key: persist }] : [])),
})

if (address != null) {
  persisted.filter.address = address
}

const columns = $computed(() => [
  {
    label: 'Timestamp',
    name: 'timestamp',
    filtered: persisted.filter.after != null || persisted.filter.after != null,
  },
  { label: 'Address', name: 'address', filtered: persisted.filter.address != null },
  { label: 'Level', name: 'level', filtered: persisted.filter.level != null },
  {
    label: 'Content',
    name: 'content',
    filtered: persisted.filter.content_prefix != null || persisted.filter.content_contains != null,
  },
])
</script>

<template>
  <record-view
    :address="address"
    :columns="columns"
    :container-class="containerClass"
    :filter="persisted.filter as any"
    type="log-entry"
  >
    <template #column-filter-timestamp>
      <div style="min-width: 200px">
        <div class="q-mb-xs">
          <schema-form-base
            v-model="persisted.filter.after"
            :schema="{ title: 'After', type: 'string', format: 'date-time', optional: true }"
          />
        </div>
        <div>
          <schema-form-base
            v-model="persisted.filter.before"
            :schema="{ title: 'Before', type: 'string', format: 'date-time', optional: true }"
          />
        </div>
      </div>
    </template>
    <template #column-filter-address>
      <div style="min-width: 200px">
        <schema-form-base
          :model-value="persisted.filter.address?.toString()"
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
              (persisted.filter.address =
                value == null ? undefined : new AddressSelector(String(value)))
          "
        />
      </div>
    </template>
    <template #column-filter-level>
      <div style="min-width: 200px">
        <schema-form-base
          v-model="persisted.filter.level"
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
            v-model="persisted.filter.content_prefix"
            :schema="{ title: 'Prefix', type: 'string', optional: true }"
          />
        </div>
        <schema-form-base
          v-model="persisted.filter.content_contains"
          :schema="{ title: 'Contains', type: 'string', optional: true }"
        />
      </div>
    </template>
  </record-view>
</template>
