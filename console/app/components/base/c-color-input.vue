<script lang="ts" setup>
const { size = 20 } = defineProps<{
  /** The swatch's diameter in pixels. */
  size?: number
}>()

const modelValue = defineModel<string>({ required: true })
</script>

<template>
  <!-- The swatch stands for the value and opens the picker, a full panel being too much to sit
  inline in a row. The picker writes hex, which is the form the value is stored and read in. -->
  <c-popover :content="{ side: 'bottom', align: 'end' }">
    <button
      class="border-default cursor-pointer rounded-full border"
      :style="{ width: `${size}px`, height: `${size}px`, background: modelValue }"
      type="button"
    />
    <template #content>
      <c-color-picker v-model="modelValue" class="p-2" />
    </template>
  </c-popover>
</template>
