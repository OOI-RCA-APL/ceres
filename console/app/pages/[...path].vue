<script lang="ts" setup>
import { useNavigation } from '@/navigation'

// An unknown path lands on home rather than an error page, since every route here is reached from
// the console's own navigation and a stale link is worth no more than a wrong turn.
const navigation = useNavigation()
await navigation.replace('/')
</script>

<template>
  <div />
</template>
