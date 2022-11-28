<template>
  <div class="self-page">
    <q-splitter v-model="state.split" class="full-height" :limits="[10, 30]">
      <template #before>
        <div class="column full-height no-wrap overflow-hidden">
          <div>
            <common-text class="q-ml-md q-py-sm" variant="title2">Units</common-text>
            <q-separator />
          </div>
          <q-list class="col-grow overflow-auto q-pt-xs scroll" dense>
            <q-item
              v-for="unit in config.data.units"
              :key="unit.name"
              clickable
              dense
              :to="`/units/${unit.name}`"
            >
              <q-item-section>
                <q-item-label class="text-no-wrap">@{{ unit.name }}</q-item-label>
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
import { useConfig } from '@/api/queries'
import CommonText from '@/components/CommonText.vue'
import { usePersisted } from '@/persistence'
import Zod from 'zod'

const StateSchema = Zod.object({
  split: Zod.number().default(20),
})

const state = usePersisted({
  schema: StateSchema,
  methods: [{ type: 'local-storage', key: 'units' }],
})

const config = useConfig()
</script>

<style lang="scss">
.self-page {
  height: calc(100vh - 50px);
}
</style>
