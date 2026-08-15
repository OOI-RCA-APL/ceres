<script lang="ts" setup>
import { useNavigation } from '@/navigation'

definePageMeta({ auth: 'admin' })

const navigation = useNavigation()
const id = $computed(() => String(navigation.route.params.id))
</script>

<template>
  <c-user-page :id />
</template>
