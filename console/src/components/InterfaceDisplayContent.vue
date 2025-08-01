<script lang="ts" setup>
import { DisplayElement, Element } from '@/api/elements'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { InterfacePath } from '@/interface'

const {
  display,
  element,
  path,
  titleClickable = false,
  isLoading = false,
} = $defineProps<{
  display: DisplayElement
  element: Element | null
  path: InterfacePath
  titleClickable?: boolean
  isLoading?: boolean
}>()

const emit = defineEmits<{
  (emit: 'title-click'): void
}>()
</script>

<template>
  <div :class="[$style.root, 'column']">
    <q-markup-table :class="$style.header" dense flat separator="cell">
      <thead>
        <q-tr no-hover>
          <q-th
            :class="titleClickable && 'cursor-pointer'"
            :tabindex="titleClickable ? '0' : '-1'"
            @click="emit('title-click')"
          >
            {{ display.title }}
          </q-th>
        </q-tr>
      </thead>
    </q-markup-table>
    <div class="col-grow items-center justify-center q-ma-xs relative-position row">
      <template v-if="element">
        <interface-element :element :path />
      </template>
      <template v-else>
        <div key="placeholder" :class="$style.placeholder" />
      </template>
      <transition appear enter-active-class="animated fadeIn" leave-active-class="animated fadeOut">
        <div :class="[$style.spinnerContainer, element != null && $style.spinnerContainerRefresh]">
          <q-spinner-orbit
            v-if="isLoading || element == null"
            key="spinner"
            :class="$style.spinner"
            color="primary"
            size="18px"
          />
        </div>
      </transition>
    </div>
  </div>
</template>

<style lang="scss" module>
:global(.dark) .root {
  background-color: $darker;
}

.header {
  background-color: $grey-1;
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
}

:global(.dark) .header {
  background-color: $dark;
}

.spinnerContainer {
  width: 16px;
  height: 16px;
  position: absolute;
  left: auto;
  right: auto;
  top: auto;
  bottom: auto;
}

.spinnerContainer.spinnerContainerRefresh {
  left: 3px;
  top: -30px;
}

.placeholder {
  min-height: 27px;
}
</style>
