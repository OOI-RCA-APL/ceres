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
      <!-- Sits on the brand fill rather than the page, so it takes the header's own foreground
      instead of the neutral one a ghost button carries by default. -->
      <c-button
        class="text-white hover:bg-white/15 hover:text-white"
        color="neutral"
        :icon="icons.drawer"
        size="sm"
        variant="ghost"
        @click="drawer.toggle()"
      />
      <c-text class="cursor-pointer" inline variant="title1" @click="navigation.go('/')">
        {{ engine.config.console.title ?? constants.defaultTitle }}
      </c-text>
      <div class="flex-1" />
      <c-utc-clock />
    </header>
    <div class="flex">
      <!-- Sticky rather than fixed, so it rides the overscroll bounce with the header and the
      page instead of holding still while they stretch. -->
      <c-drawer
        v-if="drawer.isOpen"
        class="sticky z-10 shrink-0 self-start"
        :style="{
          top: `${appHeaderHeight}px`,
          height: `calc(100dvh - ${appHeaderHeight}px)`,
          width: `${drawer.width}px`,
        }"
      />
      <main class="min-w-0 flex-1">
        <slot />
      </main>
    </div>
  </div>
</template>
