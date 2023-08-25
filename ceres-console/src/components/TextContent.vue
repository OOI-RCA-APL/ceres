<script lang="ts" setup>
import SpecialCharacter from '@/components/SpecialCharacter.vue'

const { text } = defineProps<{
  text: string
}>()

function isSpecialCharacter(character: string) {
  const code = character.charCodeAt(0)
  return code < 32 || (code >= 127 && code <= 159)
}

const chunks = $computed(() => {
  const result = []
  let current: string[] = []
  for (const character of text) {
    if (isSpecialCharacter(character)) {
      if (current.length > 0) {
        result.push({ type: 'text', value: current.join('') })
        current = []
      }

      result.push({ type: 'special', value: character })
    } else {
      current.push(character)
    }
  }

  if (current.length > 0) {
    result.push({ type: 'text', value: current.join('') })
  }

  return result
})
</script>

<template>
  <span>
    <template v-for="(chunk, i) in chunks">
      <template v-if="chunk.type === 'text'">
        <span :key="i">{{ chunk.value }}</span>
      </template>
      <template v-else>
        <special-character :key="i" :character="chunk.value" />
      </template>
    </template>
  </span>
</template>
