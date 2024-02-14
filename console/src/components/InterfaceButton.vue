<script lang="ts" setup>
import { ButtonElement } from '@/api/models'
import { getComponentProcedure } from '@/api/operations'
import ComponentProcedure from '@/components/ComponentProcedure.vue'
import icons from '@/icons'
import { useQuery } from 'vue-query'

const { element } = defineProps<{
  element: ButtonElement
}>()

let isShowingMenu = $ref(false)

const request = useQuery(['get-action', element.address, element.action], async () => {
  const procedure = await getComponentProcedure(element.address, element.action)
  if (procedure?.type === 'action') {
    return procedure
  }

  return null
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
        <component-procedure :address="element.address" :procedure="action" />
      </q-card>
    </q-menu>
  </q-btn>
</template>

<style lang="scss" module>
.menu {
  min-width: 300px;
}
</style>
