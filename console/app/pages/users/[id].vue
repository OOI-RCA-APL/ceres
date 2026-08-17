<script lang="ts" setup>
import { usePageParameter } from '@/navigation'

definePageMeta({ auth: 'admin' })

const id = usePageParameter('id')
</script>

<template>
  <c-user-page :id />
</template>
