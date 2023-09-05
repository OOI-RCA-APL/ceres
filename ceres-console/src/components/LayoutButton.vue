<script lang="ts" setup>
import { ComponentInfo, LayoutButton } from '@/api/models'
import CommonText from '@/components/CommonText.vue'
import ComponentProcedure from '@/components/ComponentProcedure.vue'
import icons from '@/icons'

const { component, button } = defineProps<{
  component: ComponentInfo
  button: LayoutButton
}>()

let isShowingMenu = $ref(false)

const action = $computed(
  () =>
    component.procedures.find(
      (procedure) => procedure.type === 'action' && procedure.name === button.action
    ) ?? null
)
</script>

<template>
  <q-btn
    :icon="isShowingMenu ? icons.arrowUp : icons.arrowDown"
    :label="button.title"
    :style="{ backgroundColor: button.color ?? undefined }"
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
          class="absolute-top-right q-ma-sm"
          flat
          icon="close"
          round
          size="6px"
          @click="isShowingMenu = false"
        />
        <common-text class="q-mb-sm" variant="th">Action / {{ button.title }}</common-text>
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
