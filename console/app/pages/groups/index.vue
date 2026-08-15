<script lang="ts" setup>
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import icons from '@/icons'

definePageMeta({ auth: 'admin' })

const engine = useEngine()

const query = useQuery({
  queryKey: ['groups'],
  queryFn: () => engine.groups.getAll(),
})

const groups = $computed(() => query.data.value ?? [])
</script>

<template>
  <c-card-page title="Groups">
    <template #header-append>
      <c-button :icon="icons.add" size="sm" to="/groups/create" variant="ghost" />
    </template>
    <div class="p-4">
      <div class="divide-default divide-y rounded-md border border-default">
        <nuxt-link
          v-for="group in groups"
          :key="group.id"
          class="hover:bg-elevated flex items-center gap-2 px-3 py-1.5"
          :to="`/groups/${group.id}`"
        >
          <c-text class="min-w-0 flex-1 truncate" variant="body2">{{ group.name }}</c-text>
          <c-text class="text-muted min-w-0 flex-1 truncate" variant="body2">
            {{ group.description }}
          </c-text>
        </nuxt-link>
        <div v-if="groups.length === 0" class="px-3 py-1.5">
          <c-text class="text-muted block" variant="body2">No groups.</c-text>
        </div>
      </div>
    </div>
  </c-card-page>
</template>
