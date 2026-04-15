<script lang="ts" setup>
import DataToken from '@/components/DataToken.vue'
import { highlight } from '@/utilities'

export type DataContentDisplay = 'default' | 'hex' | 'binary' | 'utf-8'

const { data, display = 'default' } = defineProps<{
  data: string
  display?: DataContentDisplay
}>()

function isSpecialCharacter(character: string) {
  const code = character.charCodeAt(0)
  return code < 32 || (code >= 127 && code <= 159)
}

const byteLabels = $computed(() =>
  Array.from(data, (character) => {
    const code = character.charCodeAt(0)
    if (display === 'binary') {
      return code.toString(2).padStart(8, '0')
    }
    return code.toString(16).padStart(2, '0')
  })
)

const chunks = $computed(() => {
  const chunks: { type: string; value: string }[] = []
  if (display === 'utf-8') {
    chunks.push({ type: 'text', value: highlight(data, 'log') })
    return chunks
  }

  let buffer = ''

  for (const character of data) {
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
  <span v-if="display === 'hex' || display === 'binary'">
    <data-token v-for="(byte, i) in byteLabels" :key="i" character="" :label="byte" />
  </span>
  <span v-else>
    <template v-for="(chunk, i) in chunks">
      <template v-if="chunk.type === 'text'">
        <!-- eslint-disable-next-line vue/no-v-html -->
        <span :key="i" v-html="chunk.value" />
      </template>
      <template v-else>
        <data-token :key="i" :character="chunk.value" />
      </template>
    </template>
  </span>
</template>
