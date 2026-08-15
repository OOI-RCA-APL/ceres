<script lang="ts" setup>
import { type TextVariant, variantClasses } from '@/components/base/c-text.vue'
import icons from '@/icons'

const colorMode = useColorMode()

const iconEntries = Object.entries(icons)

// Written out statically so the Tailwind scanner sees every class.
const semanticColors = [
  { name: 'primary', classes: 'bg-primary' },
  { name: 'success', classes: 'bg-success' },
  { name: 'warning', classes: 'bg-warning' },
  { name: 'error', classes: 'bg-error' },
  { name: 'info', classes: 'bg-info' },
]

// Neutral expresses itself through the surface tokens rather than a bg-neutral utility.
const surfaces = [
  { name: 'default', classes: 'bg-default' },
  { name: 'muted', classes: 'bg-muted' },
  { name: 'elevated', classes: 'bg-elevated' },
  { name: 'accented', classes: 'bg-accented' },
  { name: 'inverted', classes: 'bg-inverted' },
]

const typeRamp = Object.keys(variantClasses) as TextVariant[]

function toggleColorMode() {
  colorMode.preference = colorMode.value === 'dark' ? 'light' : 'dark'
}
</script>

<template>
  <div class="flex flex-col gap-8 p-8">
    <div class="flex items-center gap-4">
      <c-text element="h1" variant="title1">Theme</c-text>
      <c-button color="neutral" variant="outline" @click="toggleColorMode">
        {{ colorMode.value === 'dark' ? 'Switch to light' : 'Switch to dark' }}
      </c-button>
    </div>

    <section class="flex flex-col gap-3">
      <c-text element="h2" variant="title2">Semantic Colors</c-text>
      <div class="flex flex-wrap gap-4">
        <div
          v-for="color in semanticColors"
          :key="color.name"
          class="flex flex-col items-center gap-1"
        >
          <div class="h-16 w-24 rounded" :class="color.classes" />
          <c-text element="span" variant="th">{{ color.name }}</c-text>
        </div>
      </div>
    </section>

    <section class="flex flex-col gap-3">
      <c-text element="h2" variant="title2">Surfaces</c-text>
      <div class="flex flex-wrap gap-4">
        <div
          v-for="surface in surfaces"
          :key="surface.name"
          class="flex flex-col items-center gap-1"
        >
          <div class="h-16 w-24 rounded border border-accented" :class="surface.classes" />
          <c-text element="span" variant="th">{{ surface.name }}</c-text>
        </div>
      </div>
    </section>

    <section class="flex flex-col gap-3">
      <c-text element="h2" variant="title2">Type Ramp</c-text>
      <div class="flex flex-col gap-2">
        <div v-for="variant in typeRamp" :key="variant" class="flex items-baseline gap-4">
          <c-text class="w-24 shrink-0 text-muted" element="span" variant="th">
            {{ variant }}
          </c-text>
          <c-text element="span" :variant="variant">
            The five boxing wizards jump quickly. 0123456789
          </c-text>
        </div>
      </div>
    </section>

    <section class="flex flex-col gap-3">
      <c-text element="h2" variant="title2">Monospace</c-text>
      <c-text element="pre" variant="mono-lg">ceres run all --watch 0123456789</c-text>
    </section>

    <section class="flex flex-col gap-3">
      <c-text element="h2" variant="title2">Icons</c-text>
      <div class="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2">
        <div v-for="[name, icon] in iconEntries" :key="name" class="flex items-center gap-2">
          <c-icon class="size-5" :name="icon" />
          <c-text element="span" variant="description">{{ name }}</c-text>
        </div>
      </div>
    </section>
  </div>
</template>
