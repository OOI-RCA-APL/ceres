<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'

import { useEngine } from '@/api/engine'
import CardPage from '@/components/CardPage.vue'
import icons from '@/icons'

const engine = useEngine()

const query = useQuery({
  queryKey: ['groups'],
  queryFn: () => engine.groups.getAll(),
})

await query.suspense()
const groups = $computed(() => query.data.value ?? [])
</script>

<template>
  <card-page title="Groups">
    <template #header-append>
      <q-space />
      <q-btn flat :icon="icons.add" padding="none" round size="12px" to="/groups/create" />
    </template>
    <q-card-section>
      <q-card bordered flat>
        <q-list class="fit" dense separator>
          <q-item v-for="group in groups" :key="group.id" :to="`/groups/${group.id}`">
            <q-item-section>
              {{ group.name }}
            </q-item-section>
            <q-item-section>
              <q-item-label class="ellipsis text-grey-6">{{ group.description }}</q-item-label>
            </q-item-section>
          </q-item>
          <q-item v-if="groups.length === 0">
            <q-item-section>
              <q-item-label class="text-grey-6">No groups.</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card>
    </q-card-section>
  </card-page>
</template>
