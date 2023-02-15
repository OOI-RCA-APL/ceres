<template>
  <q-btn
    :class="['q-px-md', isSelected ? 'text-primary' : '']"
    dense
    flat
    :icon="isSelected ? 'arrow_drop_up' : 'arrow_drop_down'"
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
</template>

<script lang="ts" setup>
import { usePanelGroup } from '@/panel-group'

const { name } = defineProps<{
  name: string
}>()

const group = usePanelGroup()
const isSelected = $computed(() => group.isSelected(name))
</script>
