<script lang="ts" setup>
import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import { Group } from '@/api/groups'
import icons from '@/icons'
import { debouncedComputed } from '@/utilities'

const emit = defineEmits<{
  (emit: 'select', group: Group): void
}>()

const { omit, empty } = defineProps<{
  omit?: (group: Group) => boolean
  disable?: (group: Group) => boolean
  empty?: string | null
}>()

const engine = useEngine()

let search = $ref('')

const query = useQuery({
  queryKey: debouncedComputed(() => ['group-chooser', search], 100),
  queryFn: async () => {
    const text = search.trim().toLowerCase()

    let groups = await engine.groups.getAll()

    if (text !== '') {
      groups = groups.filter(
        (group) =>
          group.name.toLowerCase().includes(text) || group.description.toLowerCase().includes(text)
      )
    }

    if (omit != null) {
      groups = groups.filter((group) => !omit(group))
    }

    return groups
  },
  placeholderData: (previous) => previous,
})

const groups = $computed(() => query.data.value ?? [])
</script>

<template>
  <div class="q-pa-sm">
    <q-input
      v-model="search"
      autofocus
      class="q-mb-sm"
      dense
      label="Groups"
      outlined
      :spellcheck="false"
      @keyup.enter="
        () => {
          if (groups.length > 0) {
            emit('select', groups[0])
          }
        }
      "
    >
      <template #prepend>
        <q-icon :name="icons.search" />
      </template>
    </q-input>
    <q-card bordered flat>
      <div v-if="groups.length === 0" :class="[$style.emptyMessageText, 'q-pa-sm']">
        {{ empty ?? 'No groups found.' }}
      </div>
      <q-list v-else :class="[$style.list, 'scroll']" dense>
        <q-item
          v-for="group in groups"
          :key="group.id"
          :active="groups.length === 1"
          class="q-pb-sm"
          clickable
          :disable="disable?.(group) ?? false"
          @click="$emit('select', group)"
        >
          <q-item-section>
            <q-item-label>{{ group.name }}</q-item-label>
            <q-item-label v-if="group.description" caption>
              {{ group.description }}
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-card>
  </div>
</template>

<style lang="scss" module>
.list {
  max-height: calc(40px * 3);
}

.emptyMessageText {
  text-align: center;
  font-size: 13px;
  opacity: 0.5;
}
</style>
