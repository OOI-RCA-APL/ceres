<script lang="ts" setup>
import { ButtonElement, ComponentInfo } from '@/api/models'
import ComponentProcedure from '@/components/ComponentProcedure.vue'
import icons from '@/icons'

const { component, element } = defineProps<{
  component: ComponentInfo
  element: ButtonElement
}>()

let isShowingMenu = $ref(false)

const action = $computed(
  () =>
    component.procedures.find(
      (procedure) => procedure.type === 'action' && procedure.name === element.action
    ) ?? null
)
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
          <div class="monospace-lg">{{ component.address }}::{{ element.action }}</div>
        </div>
        <component-procedure :component="component" :procedure="action" />
      </q-card>
    </q-menu>
  </q-btn>
</template>

<style lang="scss" module>
.menu {
  min-width: 300px;
}
</style>
