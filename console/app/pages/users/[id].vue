<script lang="ts" setup>
import { useRoute } from 'vue-router'

definePageMeta({ auth: 'admin' })

const route = useRoute()
const id = $computed(() => String(route.params.id))
</script>

<template>
  <c-user-page :id />
</template>
