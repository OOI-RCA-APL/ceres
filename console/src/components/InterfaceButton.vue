<script lang="ts" setup>
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'

import { ButtonElement } from '@/api/elements'
import { useEngine } from '@/api/engine'
import Procedure from '@/components/Procedure.vue'
import icons from '@/icons'

const { element } = $defineProps<{
  element: ButtonElement
}>()

let isShowingMenu = $ref(false)

const engine = useEngine()

const request = useQuery({
  queryKey: computed(() => ['action', element.address, element.action]),
  queryFn: async () => {
    const procedure = await engine.components.getProcedure(element.address, element.action)
    if (procedure?.type === 'action') {
      return procedure
    }

    return null
  },
})

const action = $computed(() => request.data.value ?? null)
</script>

<template>
  <q-btn
    dense
    :icon="isShowingMenu ? icons.menuUp : icons.menuDown"
    :label="element.title"
    :style="{ backgroundColor: element.color ?? undefined }"
  >
    <q-menu
      v-if="action"
      v-model="isShowingMenu"
      anchor="bottom left"
      class="no-shadow"
      :offset="[0, 8]"
      persistent
      self="top left"
    >
      <q-card bordered class="q-px-sm relative-position" :class="[$style.menu, 'q-pa-sm']" flat>
        <q-btn
          class="absolute-top-right q-ma-xs"
          flat
          :icon="icons.close"
          round
          size="8px"
          @click="isShowingMenu = false"
        />
        <div class="items-center q-mb-sm q-ml-xs row">
          <div class="monospace-lg">{{ element.address }}::{{ element.action }}</div>
        </div>
        <procedure :address="element.address" :procedure="action" />
      </q-card>
    </q-menu>
  </q-btn>
</template>

<style lang="scss" module>
.menu {
  min-width: 300px;
}
</style>
