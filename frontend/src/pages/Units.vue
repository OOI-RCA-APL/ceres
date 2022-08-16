<template>
  <div class="self-page">
    <q-splitter v-model="state.split" class="full-height" :limits="[10, 30]">
      <template #before>
        <div class="column full-height no-wrap overflow-hidden">
          <common-text class="q-ml-md q-py-xs" variant="title2">Units</common-text>
          <q-separator />
          <q-list class="col-grow overflow-auto q-pt-xs scroll" dense>
            <q-item
              v-for="(unit, name) in mock.config.units"
              :key="name"
              clickable
              dense
              :to="`/units/${name}`"
            >
              <q-item-section>
                <q-item-label>@{{ name }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </div>
      </template>
      <template #after>
        <div class="full-height overflow-auto scroll">
          <router-view />
        </div>
      </template>
    </q-splitter>
  </div>
</template>

<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import mock from '@/mock'
import { usePersisted } from '@/persistence'
import Zod from 'zod'

const StateSchema = Zod.object({
  split: Zod.number().default(20),
})

const state = usePersisted({
  schema: StateSchema,
  methods: [{ type: 'local-storage', key: 'units' }],
})
</script>

<style lang="scss">
.self-page {
  height: calc(100vh - 50px);
}
</style>
