<script lang="ts" setup>
import AppBoundary from '@/AppBoundary.vue'
import HeightContainer from '@/components/HeightContainer.vue'
import icons from '@/icons'
import { usePersisted } from '@/persistence'
import { computed } from 'vue'

const { name, persist } = defineProps<{
  name: string
  defaultHeight: number
  minHeight?: number
  maxHeight?: number
  persist?: string
  containerClass?: string
}>()

const state = usePersisted({
  schema: ({ object, boolean }) =>
    object({
      isSelected: boolean().default(false),
    }),
  methods: computed(() => (persist != null ? [{ type: 'local-storage', key: persist }] : [])),
})
</script>

<template>
  <div>
    <q-btn
      :class="[
        'row',
        'full-width',
        state.isSelected && 'text-primary',
        state.isSelected && !$q.dark.isActive && 'bg-grey-1',
      ]"
      dense
      flat
      no-caps
      square
      :style="{ fontWeight: '400' }"
      @click="state.isSelected = !state.isSelected"
    >
      <div class="row" :style="{ opacity: state.isSelected ? 1 : 0.75 }">
        <q-icon :name="state.isSelected ? icons.menuUp : icons.menuDown" size="20px" />
        {{ name }}
      </div>
      <slot name="append" />
    </q-btn>
    <q-separator />
    <template v-if="state.isSelected">
      <height-container
        :class="containerClass"
        :default-height="defaultHeight"
        :max-height="maxHeight"
        :min-height="minHeight"
        :persist="persist && persist + '/height'"
      >
        <app-boundary>
          <slot />
        </app-boundary>
      </height-container>
    </template>
  </div>
</template>
