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
      <c-list>
        <c-list-item v-for="group in groups" :key="group.id" :to="`/groups/${group.id}`">
          <c-text class="min-w-0 flex-1 truncate" variant="body2">{{ group.name }}</c-text>
          <c-text class="text-muted min-w-0 flex-1 truncate" variant="body2">
            {{ group.description }}
          </c-text>
        </c-list-item>
        <c-list-item v-if="groups.length === 0">
          <c-text class="text-muted block" variant="body2">No groups.</c-text>
        </c-list-item>
      </c-list>
    </div>
  </c-card-page>
</template>
