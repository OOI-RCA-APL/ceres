<script lang="ts" setup>
import SectionCard from '@/components/SectionCard.vue'
import icons from '@/icons'

const isOpen = $ref(false)

const { size = '16px' } = defineProps<{
  title: string
  size?: string
}>()
</script>

<template>
  <q-icon
    class="cursor-pointer q-ml-sm"
    color="grey-5"
    :name="icons.help"
    :size="size"
    @click="isOpen = true"
  >
    <q-dialog v-model="isOpen">
      <section-card padding style="width: 100%; max-width: 1000px" :title="title">
        <template #header-append>
          <q-space />
          <q-btn color="grey-8" dense flat :icon="icons.close" round @click="isOpen = false" />
        </template>
        <slot />
      </section-card>
    </q-dialog>
  </q-icon>
</template>
