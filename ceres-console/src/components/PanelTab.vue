<template>
  <q-btn
    align="left"
    :class="[
      'row',
      'items-center',
      'q-px-md',
      'col-grow',
      isSelected && 'text-primary',
      isSelected && !$q.dark.isActive && 'bg-grey-1',
    ]"
    dense
    flat
    :icon="isSelected ? icons.dropUp : icons.dropDown"
    no-caps
    square
    :style="{ fontWeight: '400' }"
    @click="group.toggle(name)"
  >
    <template v-if="$slots.default">
      <slot />
    </template>
    <template v-else>
      {{ name }}
    </template>
  </q-btn>
  <q-separator vertical />
</template>

<script lang="ts" setup>
import icons from '@/icons'
import { usePanelGroup } from '@/panel-group'

const { name } = defineProps<{
  name: string
}>()

const group = usePanelGroup()
const isSelected = $computed(() => group.isSelected(name))
</script>
