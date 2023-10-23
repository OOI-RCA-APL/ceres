<script lang="ts">
const translation: Readonly<Record<number, string>> = {
  [9]: '\\t', // Tab
  [10]: '\\n', // Line Feed
  [13]: '\\r', // Carriage Return
}
</script>

<script lang="ts" setup>
const { character } = defineProps<{
  character: string
}>()

const rendered = $computed(() => {
  const code = character.charCodeAt(0)
  // If the character code has an explicit rendering, use that.
  const translated = translation[code]
  if (translated != null) {
    return translated
  }

  // Otherwise, just render the hex code.
  return '0x' + code.toString(16).padStart(2, '0')
})
</script>

<template>
  <span :class="$style.root">
    {{ rendered }}
  </span>
</template>

<style lang="scss" module>
.root {
  background-color: $grey-3;
  border-radius: 4px;
  color: $grey-10;
  color: black;
  margin: 0 0.15em;
  padding: 0.2em;
  position: relative;
}

:global(.dark) .root {
  background-color: darken($grey-9, 6%);
  color: $grey-2;
}
</style>
