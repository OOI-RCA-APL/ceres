<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { ref } from 'vue'

import { useEngine } from '@/api/engine'
import CardPage from '@/components/CardPage.vue'
import { useDialogs } from '@/dialogs'
import { guard } from '@/errors'
import icons from '@/icons'
import { useNotify } from '@/notify'

const engine = useEngine()
const dialogs = useDialogs()
const notify = useNotify()

const query = useQuery({
  queryKey: ['groups'],
  queryFn: () => engine.groups.getAll(),
})

await query.suspense()
const groups = $computed(() => query.data.value ?? [])

const newGroupName = ref('')

function promptCreate() {
  dialogs
    .show({
      title: 'Create Group',
      prompt: {
        model: newGroupName.value,
        type: 'text',
        label: 'Group Name',
        outlined: true,
        dense: true,
      },
      ok: { label: 'Create' },
      cancel: { label: 'Cancel', flat: true, color: 'grey' },
    })
    .onOk(async (name: string) => {
      await guard(engine.groups.create({ name: name.trim() }), () => {
        notify.error('Failed to create group.')
      })
      notify.success('Group created.')
      await query.refetch()
    })
}
</script>

<template>
  <card-page title="Groups">
    <template #header-append>
      <q-space />
      <q-btn flat :icon="icons.add" padding="none" round size="12px" @click="promptCreate" />
    </template>
    <q-card-section>
      <q-card bordered flat>
        <q-list class="fit" dense separator>
          <q-item v-for="group in groups" :key="group.id" :to="`/groups/${group.id}`">
            <q-item-section>
              <q-item-label>{{ group.name }}</q-item-label>
              <q-item-label v-if="group.description" caption>
                {{ group.description }}
              </q-item-label>
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
