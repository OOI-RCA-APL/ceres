<script lang="ts" setup>
const colorMode = useColorMode()

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

const typeRamp = [
  { variant: 'title1', classes: 'text-[22px] font-light leading-normal' },
  { variant: 'title2', classes: 'text-lg font-light leading-normal' },
  { variant: 'title3', classes: 'text-sm font-light leading-normal' },
  { variant: 'body1', classes: 'text-base font-normal leading-6 tracking-[0.03125em]' },
  { variant: 'body2', classes: 'text-sm font-normal leading-6 tracking-[0.03125em]' },
  { variant: 'th', classes: 'text-xs font-medium' },
  { variant: 'description', classes: 'text-[11px] text-muted' },
  { variant: 'value', classes: 'text-lg font-light leading-normal' },
]

function toggleColorMode() {
  colorMode.preference = colorMode.value === 'dark' ? 'light' : 'dark'
}
</script>

<template>
  <div class="flex flex-col gap-8 p-8">
    <div class="flex items-center gap-4">
      <h1 class="text-[22px] font-light leading-normal">Theme</h1>
      <button
        class="rounded border border-accented px-3 py-1 text-sm"
        type="button"
        @click="toggleColorMode"
      >
        {{ colorMode.value === 'dark' ? 'Switch to light' : 'Switch to dark' }}
      </button>
    </div>

    <section class="flex flex-col gap-3">
      <h2 class="text-lg font-light leading-normal">Semantic Colors</h2>
      <div class="flex flex-wrap gap-4">
        <div
          v-for="color in semanticColors"
          :key="color.name"
          class="flex flex-col items-center gap-1"
        >
          <div class="h-16 w-24 rounded" :class="color.classes" />
          <span class="text-xs font-medium">{{ color.name }}</span>
        </div>
      </div>
    </section>

    <section class="flex flex-col gap-3">
      <h2 class="text-lg font-light leading-normal">Surfaces</h2>
      <div class="flex flex-wrap gap-4">
        <div
          v-for="surface in surfaces"
          :key="surface.name"
          class="flex flex-col items-center gap-1"
        >
          <div class="h-16 w-24 rounded border border-accented" :class="surface.classes" />
          <span class="text-xs font-medium">{{ surface.name }}</span>
        </div>
      </div>
    </section>

    <section class="flex flex-col gap-3">
      <h2 class="text-lg font-light leading-normal">Type Ramp</h2>
      <div class="flex flex-col gap-2">
        <div v-for="entry in typeRamp" :key="entry.variant" class="flex items-baseline gap-4">
          <span class="w-24 shrink-0 text-xs font-medium text-muted">{{ entry.variant }}</span>
          <span :class="entry.classes">The five boxing wizards jump quickly. 0123456789</span>
        </div>
      </div>
    </section>

    <section class="flex flex-col gap-3">
      <h2 class="text-lg font-light leading-normal">Monospace</h2>
      <pre class="font-mono text-sm">ceres run all --watch  0123456789</pre>
    </section>
  </div>
</template>
