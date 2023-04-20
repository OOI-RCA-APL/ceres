<script lang="ts" setup>
import { ComponentInfo, LayoutCarousel } from '@/api/models'
import LayoutNode from '@/components/LayoutNode.vue'
import { LayoutPath } from '@/layout'
import { usePersisted } from '@/persistence'
import { QCarousel } from 'quasar'
import { computed } from 'vue'

const { component, node, path } = defineProps<{
  component: ComponentInfo
  node: LayoutCarousel
  path: LayoutPath
}>()

const persisted = usePersisted({
  schema: ({ object, number }) =>
    object({
      index: number().default(0),
    }),
  methods: computed(() => [
    { type: 'local-storage', key: `state/layout-carousel/${component.address}/${path.join('.')}` },
  ]),
})

const height = $computed(() => {
  if (node.height == null) {
    return 'auto'
  }
  if (typeof node.height === 'number') {
    return node.height + 'px'
  }

  return node.height
})
</script>

<template>
  <q-card bordered class="q-pt-sm q-px-sm" flat>
    <q-carousel
      v-model="persisted.index"
      animated
      :height="height"
      keep-alive
      swipeable
      :transition-duration="500"
      transition-next="slide-left"
      transition-prev="slide-right"
    >
      <q-carousel-slide
        v-for="(child, i) in node.children"
        :key="i"
        class="column full-height justify-center q-pa-none"
        :name="i"
      >
        <layout-node :component="component" :node="child" :path="[...path, i]" />
      </q-carousel-slide>
    </q-carousel>
    <div class="items-center justify-center q-py-xs row">
      <q-btn
        v-for="(_, i) in node.children"
        :key="i"
        :aria-label="'Slide ' + (i + 1)"
        color="primary"
        flat
        round
        size="6px"
        @click="persisted.index = i"
      >
        <q-icon name="circle" :style="i !== persisted.index && { opacity: 0.25 }" />
      </q-btn>
    </div>
  </q-card>
</template>
