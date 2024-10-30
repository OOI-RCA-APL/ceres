<script lang="ts" setup>
import SpecialCharacter from '@/components/SpecialCharacter.vue'
import { highlight } from '@/utilities'

const { text } = $defineProps<{
  text: string
}>()

function isSpecialCharacter(character: string) {
  const code = character.charCodeAt(0)
  return code < 32 || (code >= 127 && code <= 159)
}

const chunks = $computed(() => {
  const chunks = []
  let buffer = ''

  for (const character of text) {
    if (isSpecialCharacter(character)) {
      if (buffer.length > 0) {
        chunks.push({ type: 'text', value: highlight(buffer, 'log') })
        buffer = ''
      }

      chunks.push({ type: 'special', value: character })
    } else {
      buffer += character
    }
  }

  if (buffer.length > 0) {
    chunks.push({ type: 'text', value: highlight(buffer, 'log') })
  }

  return chunks
})
</script>

<template>
  <span>
    <template v-for="(chunk, i) in chunks">
      <template v-if="chunk.type === 'text'">
        <!-- eslint-disable-next-line vue/no-v-html -->
        <span :key="i" v-html="chunk.value" />
      </template>
      <template v-else>
        <special-character :key="i" :character="chunk.value" />
      </template>
    </template>
  </span>
</template>
