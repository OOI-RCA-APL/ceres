<script lang="ts" setup>
const { size = 20 } = defineProps<{
  /** The swatch's diameter in pixels. */
  size?: number
}>()

const modelValue = defineModel<string>({ required: true })
</script>

<template>
  <!-- The swatch is the control rather than a preview beside one, a native color input being a
  color well already. Its own chrome is cleared so the dot is the whole of what is drawn. -->
  <input
    v-model="modelValue"
    :class="$style.swatch"
    :style="{ width: `${size}px`, height: `${size}px` }"
    type="color"
  />
</template>

<style module>
.swatch {
  padding: 0;
  border: 1px solid var(--ui-border);
  border-radius: 50%;
  background: none;
  cursor: pointer;
  appearance: none;
}

/* The well fills the control edge to edge, which needs the browser's own padding and border
around the drawn color removed in each engine's spelling of it. */
.swatch::-webkit-color-swatch-wrapper {
  padding: 0;
}

.swatch::-webkit-color-swatch,
.swatch::-moz-color-swatch {
  border: none;
  border-radius: 50%;
}
</style>
