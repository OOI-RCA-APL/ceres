<script lang="ts">
const translation: Record<number, string> = {
  [0]: 'NUL',
  [1]: 'SOH',
  [2]: 'STX',
  [3]: 'ETX',
  [4]: 'EOT',
  [5]: 'ENQ',
  [6]: 'ACK',
  [7]: 'BEL',
  [8]: 'BS',
  [9]: '⇥', // Tab / HT / '\t'
  [10]: '↵', // Line Feed / LF / '\n'
  [11]: 'VT',
  [12]: 'FF',
  [13]: '⇤', // Carriage Return / CR / '\r'
  [14]: 'SO',
  [15]: 'SI',
  [16]: 'DLE',
  [17]: 'DC1',
  [18]: 'DC2',
  [19]: 'DC3',
  [20]: 'DC4',
  [21]: 'NAK',
  [22]: 'SYN',
  [23]: 'ETB',
  [24]: 'CAN',
  [25]: 'EM',
  [26]: 'SUB',
  [27]: 'ESC',
  [28]: 'FS',
  [29]: 'GS',
  [30]: 'RS',
  [31]: 'US',
}
</script>

<script lang="ts" setup>
const { character } = defineProps<{
  character: string
}>()

const rendered = $computed(() => {
  const translated = translation[character.charCodeAt(0)]
  if (translated != null) {
    return translated
  }

  const encoded = JSON.stringify(character)
  return encoded.slice(1, encoded.length - 1)
})
</script>

<template>
  <span :class="$style.root">
    {{ rendered }}
    <span :class="$style.background" />
  </span>
</template>

<style lang="scss" module>
.root {
  margin: 0 0.2em;
  position: relative;
  padding: 0.2em;
  color: black;
}

.background {
  position: absolute;
  top: 2px;
  left: 0;
  right: 0;
  bottom: 2px;
  background-color: $grey-4;
  opacity: 0.4;
  border-radius: 4px;
}
:global(.dark) .root {
  color: white;
}

:global(.dark) .background {
  background-color: $grey-8;
}
</style>
