<script lang="ts" setup>
import { ComponentInfo, DisplayElement, Element } from '@/api/models'
import InterfaceElement from '@/components/InterfaceElement.vue'
import { InterfacePath } from '@/interface'

const {
  component,
  display,
  element,
  path,
  titleClickable = false,
  isLoading = false,
} = defineProps<{
  component: ComponentInfo
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
    <q-markup-table dense flat separator="cell">
      <thead :class="$style.header">
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
    <div class="col-grow items-center justify-center q-pa-xs relative-position row">
      <template v-if="element">
        <interface-element :component="component" :element="element" :path="path" />
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
  background-color: #131313;
}

.header {
  background-color: $grey-2;
}

:global(.dark) .header {
  background-color: #1d1d1d;
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
  left: 4px;
  top: -26px;
}

.placeholder {
  min-height: 27px;
}
</style>
@/interface
