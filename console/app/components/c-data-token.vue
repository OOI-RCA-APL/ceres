<script lang="ts">
const translation: Readonly<Record<number, string>> = {
  [9]: '\\t', // Tab
  [10]: '\\n', // Line Feed
  [13]: '\\r', // Carriage Return
}
</script>

<script lang="ts" setup>
const { character, label } = defineProps<{
  character: string
  label?: string
}>()

const rendered = $computed(() => {
  if (label != null) {
    return label
  }

  const code = character.charCodeAt(0)
  const translated = translation[code]
  if (translated != null) {
    return translated
  }

  return '0x' + code.toString(16).padStart(2, '0')
})
</script>

<template>
  <span class="bg-accented text-default relative mx-[0.15em] rounded p-[0.2em]">
    {{ rendered }}
  </span>
</template>
