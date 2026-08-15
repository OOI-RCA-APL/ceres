<script lang="ts" setup>
import icons from '@/icons'
import { useNavigation } from '@/navigation'

defineProps<{
  title: string
}>()

const navigation = useNavigation()
</script>

<template>
  <div class="flex min-h-full flex-col items-center bg-(--console-page) px-2 py-10">
    <div class="border-default relative w-full max-w-[440px] rounded-lg border bg-(--console-card)">
      <div class="pr-4">
        <div class="flex items-center">
          <!-- Parked outside the card, since the card's width is the page's measure and a control
          that leaves the page should not eat into it. Too far out to fit on a narrow screen. -->
          <c-tooltip text="Back">
            <c-button
              class="absolute top-2 -left-[46px] hidden opacity-30 transition-opacity hover:opacity-50 sm:flex"
              color="neutral"
              :icon="icons.arrowLeft"
              variant="ghost"
              @click="navigation.back()"
            />
          </c-tooltip>
          <c-text class="mx-4 my-2 grow" element="h1" variant="title1">{{ title }}</c-text>
          <slot name="header-append" />
        </div>
        <slot name="subtitle" />
      </div>
      <c-separator />
      <slot />
    </div>
    <slot name="sections" />
  </div>
</template>
