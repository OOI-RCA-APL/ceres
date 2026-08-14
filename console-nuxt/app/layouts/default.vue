<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import { appHeaderHeight } from '@/components/c-full-page.vue'
import constants from '@/constants'
import { useDrawer } from '@/drawer'
import icons from '@/icons'
import { useNavigation } from '@/navigation'

const engine = useEngine()
const drawer = useDrawer()
const navigation = useNavigation()
</script>

<!-- The window is the scroll container, which is what lets page headers and the workspace tab
strip pin with `position: sticky` and the scroll-memory helpers read `window.scrollY`. -->
<template>
  <div>
    <header
      class="sticky top-0 z-10 flex items-center gap-3 bg-primary px-3 text-white"
      :style="{ height: `${appHeaderHeight}px` }"
    >
      <c-button
        color="neutral"
        :icon="icons.drawer"
        size="sm"
        variant="ghost"
        @click="drawer.toggle()"
      />
      <c-text class="cursor-pointer" element="span" variant="title1" @click="navigation.go('/')">
        {{ engine.config.console.title ?? constants.defaultTitle }}
      </c-text>
      <div class="flex-1" />
      <c-utc-clock />
    </header>
    <aside
      v-if="drawer.isOpen"
      class="fixed bottom-0 z-10 overflow-y-auto border-r border-accented bg-default"
      :style="{ top: `${appHeaderHeight}px`, width: `${drawer.width}px` }"
    >
      <c-text class="p-4" variant="description">The component tree lands in slice 3.</c-text>
    </aside>
    <main :style="{ marginLeft: drawer.isOpen ? `${drawer.width}px` : undefined }">
      <slot />
    </main>
  </div>
</template>
