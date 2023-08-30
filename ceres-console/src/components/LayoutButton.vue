<script lang="ts" setup>
import { ComponentInfo, LayoutButton } from '@/api/models'
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
      v-model="isShowingMenu"
      anchor="bottom left"
      class="no-shadow"
      :offset="[0, 8]"
      persistent
      self="top left"
    >
      <q-card bordered class="q-pt-sm q-px-sm">
        <component-procedure v-if="action" :component="component" :procedure="action" />
      </q-card>
    </q-menu>
  </q-btn>
</template>
