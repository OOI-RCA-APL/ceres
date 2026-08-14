<script lang="ts" setup>
import { useEngine } from '@/api/engine'
import constants from '@/constants'
import { useDrawer } from '@/drawer'
import icons from '@/icons'
import { useNavigation } from '@/navigation'

const engine = useEngine()
const drawer = useDrawer()
const navigation = useNavigation()
</script>

<template>
  <div class="flex h-screen flex-col">
    <header class="flex shrink-0 items-center gap-3 bg-primary px-3 py-2 text-white">
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
    <div class="flex min-h-0 flex-1">
      <aside
        v-if="drawer.isOpen"
        class="shrink-0 overflow-y-auto border-r border-accented"
        :style="{ width: `${drawer.width}px` }"
      >
        <c-text class="p-4" variant="description">The component tree lands in slice 3.</c-text>
      </aside>
      <main class="min-w-0 flex-1 overflow-y-auto">
        <slot />
      </main>
    </div>
  </div>
</template>
