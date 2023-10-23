<script lang="ts" setup>
import { CarouselElement, ComponentInfo } from '@/api/models'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { InterfacePath } from '@/interface'
import { usePersisted } from '@/persistence'
import { QCarousel } from 'quasar'
import { computed } from 'vue'

const { component, element, path } = defineProps<{
  component: ComponentInfo
  element: CarouselElement
  path: InterfacePath
}>()

const persisted = usePersisted({
  schema: ({ object, number }) =>
    object({
      index: number().default(0),
    }),
  methods: computed(() => [
    {
      type: 'local-storage',
      key: `state/interface-carousel/${component.address}/${path.join('.')}`,
    },
  ]),
})

const height = $computed(() => {
  if (element.height == null) {
    return 'auto'
  }
  if (typeof element.height === 'number') {
    return element.height + 'px'
  }

  return element.height
})
</script>

<template>
  <div>
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
          v-for="(child, i) in element.children"
          :key="i"
          class="column full-height justify-center q-pa-none"
          :name="i"
        >
          <interface-element :component="component" :element="child" :path="[...path, i]" />
        </q-carousel-slide>
      </q-carousel>
      <div class="items-center justify-center q-py-xs row">
        <q-btn
          v-for="(_, i) in element.children"
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
  </div>
</template>
@/interface
