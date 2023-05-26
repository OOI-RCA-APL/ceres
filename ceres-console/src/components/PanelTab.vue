<script lang="ts" setup>
import icons from '@/icons'
import { usePanelGroup } from '@/panel-group'

const { name } = defineProps<{
  name: string
}>()

const group = usePanelGroup()
const isSelected = $computed(() => group.isSelected(name))
</script>

<template>
  <q-btn
    :class="[
      'row',
      'items-center',
      'col',
      isSelected && 'text-primary',
      isSelected && !$q.dark.isActive && 'bg-grey-1',
    ]"
    dense
    flat
    no-caps
    square
    :style="{ fontWeight: '400' }"
    @click="group.toggle(name)"
  >
    <div class="items-center row" :style="{ opacity: isSelected ? 1 : 0.75 }">
      <q-icon :name="isSelected ? icons.arrowUp : icons.arrowDown" size="20px" />
      <template v-if="$slots.default">
        <slot />
      </template>
      <template v-else>
        {{ name }}
      </template>
    </div>
    <slot name="append" />
  </q-btn>
  <q-separator vertical />
</template>
